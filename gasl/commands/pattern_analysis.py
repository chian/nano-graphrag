"""
Pattern Analysis command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class PatternAnalysisHandler(CommandHandler):
    """Handles pattern analysis commands: CLUSTER, DETECT, GROUP, ANALYZE."""
    
    def __init__(self, state_store, context_store, llm_func=None):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["CLUSTER", "DETECT", "GROUP", "ANALYZE"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute pattern analysis command."""
        try:
            if command.command_type == "CLUSTER":
                return self._execute_cluster(command)
            elif command.command_type == "DETECT":
                return self._execute_detect(command)
            elif command.command_type == "GROUP":
                return self._execute_group(command)
            elif command.command_type == "ANALYZE":
                return self._execute_analyze(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown pattern analysis command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_cluster(self, command: Command) -> ExecutionResult:
        """Execute CLUSTER command using LLM."""
        args = command.args
        variable = args["variable"]
        clustering_criteria = args["clustering_criteria"]
        
        print(f"DEBUG: CLUSTER - variable: {variable}, criteria: {clustering_criteria}")
        
        # Get data to cluster
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            # Simple built-in clustering
            clustered_data = self._simple_cluster(data, clustering_criteria)
        else:
            # LLM-based clustering
            clustered_data = self._llm_cluster(data, clustering_criteria)
        
        # Update the state variable with clustered results
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = clustered_data
                self.state_store._save_state()
        
        print(f"DEBUG: CLUSTER - clustered {len(clustered_data)} items")
        
        return self._create_result(
            command=command,
            status="success",
            data=clustered_data,
            count=len(clustered_data),
            provenance=[self._create_provenance("cluster", "cluster",
                                               variable=variable, clustering_criteria=clustering_criteria)]
        )
    
    def _execute_detect(self, command: Command) -> ExecutionResult:
        """Execute DETECT command using LLM."""
        args = command.args
        variable = args["variable"]
        pattern_rules = args["pattern_rules"]
        
        print(f"DEBUG: DETECT - variable: {variable}, rules: {pattern_rules}")
        
        # Get data to analyze
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for DETECT command")
        
        # Create prompt for pattern detection
        prompt = self._create_detect_prompt(data, pattern_rules)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: DETECT - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            detect_result = json.loads(llm_response)
            detected_patterns = detect_result.get("detected_patterns", [])
            
            # Store detected patterns in context
            self.context_store.set("detected_patterns", detected_patterns)
            
            print(f"DEBUG: DETECT - detected {len(detected_patterns)} patterns")
            
            return self._create_result(
                command=command,
                status="success",
                data=detected_patterns,
                count=len(detected_patterns),
                provenance=[self._create_provenance("detect", "detect",
                                                   variable=variable, pattern_rules=pattern_rules)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM pattern detection response as JSON")
    
    def _execute_group(self, command: Command) -> ExecutionResult:
        """Execute GROUP command."""
        args = command.args
        variable = args["variable"]
        group_criteria = args["group_criteria"]
        group_instruction = args.get("group_instruction", "")
        
        print(f"DEBUG: GROUP - variable: {variable}, criteria: {group_criteria}")
        
        # Get data to group
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform grouping
        groups = {}
        
        for item in data:
            # Determine group key based on criteria
            group_key = self._get_group_key(item, group_criteria)
            
            if group_key not in groups:
                groups[group_key] = {
                    "group_name": group_key,
                    "group_criteria": group_criteria,
                    "items": [],
                    "count": 0
                }
            
            groups[group_key]["items"].append(item)
            groups[group_key]["count"] += 1
        
        # Convert to list format
        grouped_data = list(groups.values())
        
        # Update the state variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = grouped_data
                self.state_store._save_state()
        
        print(f"DEBUG: GROUP - created {len(grouped_data)} groups")
        
        return self._create_result(
            command=command,
            status="success",
            data=grouped_data,
            count=len(grouped_data),
            provenance=[self._create_provenance("group", "group",
                                               variable=variable, group_criteria=group_criteria)]
        )
    
    def _execute_analyze(self, command: Command) -> ExecutionResult:
        """Execute ANALYZE command using LLM."""
        args = command.args
        variable = args["variable"]
        analysis_type = args["analysis_type"]
        
        print(f"DEBUG: ANALYZE - variable: {variable}, type: {analysis_type}")
        
        # Get data to analyze
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for ANALYZE command")
        
        # Create prompt for analysis
        prompt = self._create_analyze_prompt(data, analysis_type)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: ANALYZE - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            analysis_result = json.loads(llm_response)
            
            # Store analysis in context
            self.context_store.set("analysis_result", analysis_result)
            
            print(f"DEBUG: ANALYZE - completed {analysis_type} analysis")
            
            return self._create_result(
                command=command,
                status="success",
                data=analysis_result,
                count=1,
                provenance=[self._create_provenance("analyze", "analyze",
                                                   variable=variable, analysis_type=analysis_type)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM analysis response as JSON")
    
    def _simple_cluster(self, data: List[Dict], criteria: str) -> List[Dict]:
        """Simple built-in clustering without LLM."""
        clustered_data = []
        
        # Simple clustering by entity type
        if "entity_type" in criteria.lower():
            clusters = {}
            for item in data:
                entity_type = item.get("entity_type", "UNKNOWN")
                if entity_type not in clusters:
                    clusters[entity_type] = []
                clusters[entity_type].append(item)
            
            # Add cluster information to items
            for cluster_name, items in clusters.items():
                for item in items:
                    new_item = {**item}
                    new_item["cluster"] = cluster_name
                    new_item["cluster_size"] = len(items)
                    clustered_data.append(new_item)
        
        # Simple clustering by description keywords
        elif "research" in criteria.lower():
            clusters = {"asthma": [], "influenza": [], "allergy": [], "other": []}
            
            for item in data:
                description = item.get("description", "").lower()
                assigned = False
                
                for keyword in ["asthma", "influenza", "allergy"]:
                    if keyword in description:
                        clusters[keyword].append(item)
                        assigned = True
                        break
                
                if not assigned:
                    clusters["other"].append(item)
            
            # Add cluster information
            for cluster_name, items in clusters.items():
                for item in items:
                    new_item = {**item}
                    new_item["cluster"] = cluster_name
                    new_item["cluster_size"] = len(items)
                    clustered_data.append(new_item)
        
        else:
            # Default: no clustering, just add empty cluster field
            for item in data:
                new_item = {**item}
                new_item["cluster"] = "default"
                new_item["cluster_size"] = len(data)
                clustered_data.append(new_item)
        
        return clustered_data
    
    def _llm_cluster(self, data: List[Dict], criteria: str) -> List[Dict]:
        """LLM-based clustering."""
        prompt = self._create_cluster_prompt(data, criteria)
        
        try:
            llm_response = self.llm_func.call(prompt)
            import json
            cluster_result = json.loads(llm_response)
            return cluster_result.get("clustered_items", data)
        except Exception:
            # Fallback to simple clustering
            return self._simple_cluster(data, criteria)
    
    def _get_group_key(self, item: Dict, criteria: str) -> str:
        """Get group key for an item based on criteria."""
        if criteria == "entity_type":
            return item.get("entity_type", "UNKNOWN")
        elif criteria == "research_area":
            description = item.get("description", "").lower()
            if "asthma" in description:
                return "asthma_research"
            elif "influenza" in description:
                return "influenza_research"
            elif "allergy" in description:
                return "allergy_research"
            else:
                return "other_research"
        else:
            # Default grouping
            return "default_group"
    
    def _create_cluster_prompt(self, data: Any, criteria: str) -> str:
        """Create prompt for LLM clustering."""
        prompt = f"""Cluster the provided data according to this criteria: {criteria}

Data to cluster:
{self._format_data_for_llm(data)}

Instructions:
1. Group similar items together based on the criteria
2. Assign each item to a cluster
3. Add cluster information to each item
4. Return your results as a JSON object with this structure:
{{
  "clustered_items": [
    // Array of items with added cluster fields
  ],
  "cluster_summary": {{
    "total_clusters": 0,
    "clustering_criteria": "{criteria}",
    "cluster_names": ["cluster1", "cluster2", ...]
  }}
}}

Be consistent in your clustering approach.
"""
        return prompt
    
    def _create_detect_prompt(self, data: Any, pattern_rules: str) -> str:
        """Create prompt for LLM pattern detection."""
        prompt = f"""Detect patterns in the provided data according to these rules: {pattern_rules}

Data to analyze:
{self._format_data_for_llm(data)}

Instructions:
1. Look for patterns, trends, or recurring themes in the data
2. Identify interesting relationships or structures
3. Return your results as a JSON object with this structure:
{{
  "detected_patterns": [
    {{
      "pattern_name": "pattern description",
      "pattern_type": "type of pattern",
      "instances": ["list of examples"],
      "confidence": 0.85,
      "description": "detailed explanation"
    }},
    ...
  ],
  "pattern_summary": {{
    "total_patterns": 0,
    "detection_rules": "{pattern_rules}",
    "data_coverage": "percentage of data involved in patterns"
  }}
}}

Focus on meaningful and actionable patterns.
"""
        return prompt
    
    def _create_analyze_prompt(self, data: Any, analysis_type: str) -> str:
        """Create prompt for LLM analysis."""
        prompt = f"""Perform {analysis_type} analysis on the provided data.

Data to analyze:
{self._format_data_for_llm(data)}

Instructions:
1. Conduct a thorough {analysis_type} analysis
2. Provide insights, trends, and key findings
3. Return your results as a JSON object with this structure:
{{
  "analysis_type": "{analysis_type}",
  "key_findings": [
    "finding 1",
    "finding 2",
    ...
  ],
  "insights": [
    "insight 1",
    "insight 2",
    ...
  ],
  "recommendations": [
    "recommendation 1",
    "recommendation 2",
    ...
  ],
  "data_summary": {{
    "total_items_analyzed": 0,
    "analysis_confidence": 0.9,
    "methodology": "description of analysis approach"
  }}
}}

Provide actionable insights and clear explanations.
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
