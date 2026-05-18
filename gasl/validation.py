"""
LLM-based validation system for GASL commands.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional
from .llm.argo_bridge import ArgoBridgeLLM


class LLMJudgeValidator:
    """LLM-based validator to judge if commands accomplished their intended work."""
    
    def __init__(self, llm_func):
        self.llm_func = llm_func

    def _llm_for_path_semantics(self):
        if hasattr(self.llm_func, "clone"):
            current_model = getattr(self.llm_func, "model", "") or ""
            model = os.getenv("PATH_SEMANTICS_MODEL", "")
            if not model:
                if "mini" in current_model.lower():
                    model = os.getenv("PROCESS_LARGE_MODEL", "gpt-5.5")
                else:
                    model = current_model
            return self.llm_func.clone(model=model, reasoning_effort=os.getenv("PATH_SEMANTICS_REASONING", "high"))
        return self.llm_func
    
    def validate_command_success(self, command_type: str, command_args: Dict[str, Any], 
                                result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate if a command actually accomplished its intended work."""
        
        if command_type == "FIND":
            return self._validate_find(command_args, result_data, result_count)
        elif command_type == "UPDATE":
            return self._validate_update(command_args, result_data, result_count)
        elif command_type == "PROCESS":
            return self._validate_process(command_args, result_data, result_count)
        elif command_type == "CLASSIFY":
            return self._validate_classify(command_args, result_data, result_count)
        elif command_type == "COUNT":
            return self._validate_count(command_args, result_data, result_count)
        elif command_type == "AGGREGATE":
            return self._validate_aggregate(command_args, result_data, result_count)
        elif command_type == "GENERATE":
            return self._validate_generate(command_args, result_data, result_count)
        elif command_type == "GRAPHWALK":
            return self._validate_graphwalk(command_args, result_data, result_count)
        else:
            return {"valid": True, "reason": "No specific validation for this command type"}
    
    def _validate_find(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate FIND command success."""
        criteria = args.get("criteria", "")
        target = args.get("target", "nodes")
        
        prompt = f"""You are validating a FIND command that was supposed to find {target} matching criteria: {criteria}

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this FIND command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it find the right type of data ({target})?
2. Do the results match the criteria ({criteria})?
3. Are the results meaningful and not empty/trivial?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_update(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate UPDATE command success."""
        variable = args.get("variable", "")
        instruction = args.get("instruction", "")
        
        prompt = f"""You are validating an UPDATE command that was supposed to update variable '{variable}' with instruction: {instruction}

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this UPDATE command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it update the specified variable?
2. Did it apply the instruction correctly?
3. Are the results meaningful and not just copying data around?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_process(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate PROCESS command success."""
        variable = args.get("variable", "")
        instruction = args.get("instruction", "")
        
        prompt = f"""You are validating a PROCESS command that was supposed to process variable '{variable}' with instruction: {instruction}

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this PROCESS command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it process the data according to the instruction?
2. Did it add new fields, filter data, or transform it meaningfully?
3. Are the results different from the input (not just copying)?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_classify(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate CLASSIFY command success."""
        variable = args.get("variable", "")
        instruction = args.get("instruction", "")
        
        prompt = f"""You are validating a CLASSIFY command that was supposed to classify variable '{variable}' with instruction: {instruction}

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this CLASSIFY command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it add category fields to the data?
2. Are the classifications meaningful and consistent?
3. Did it follow the classification instruction?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_count(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate COUNT command success."""
        field_name = args.get("field_name", "")
        result_var = args.get("result_var", "")
        
        prompt = f"""You are validating a COUNT command that was supposed to count field '{field_name}' and store results in '{result_var}'

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this COUNT command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it create meaningful count statistics?
2. Are the counts accurate and useful?
3. Did it store results in the specified variable?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_aggregate(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate AGGREGATE command success."""
        variable = args.get("variable", "")
        by_field = args.get("by_field", "")
        operation = args.get("operation", "")
        
        prompt = f"""You are validating an AGGREGATE command that was supposed to aggregate variable '{variable}' by '{by_field}' using '{operation}'

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this AGGREGATE command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it group data by the specified field?
2. Did it apply the aggregation operation correctly?
3. Are the results meaningful and properly structured?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_generate(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate GENERATE command success."""
        content_type = args.get("content_type", "")
        source_variable = args.get("source_variable", "")
        
        prompt = f"""You are validating a GENERATE command that was supposed to generate '{content_type}' from variable '{source_variable}'

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this GENERATE command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it generate the specified content type?
2. Is the generated content useful and well-structured?
3. Does it relate to the source data appropriately?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)
    
    def _validate_graphwalk(self, args: Dict[str, Any], result_data: Any, result_count: int) -> Dict[str, Any]:
        """Validate GRAPHWALK command success."""
        from_variable = args.get("from_variable", "")
        relationship_types = args.get("relationship_types", "")
        depth = args.get("depth", "1")
        
        prompt = f"""You are validating a GRAPHWALK command that was supposed to walk from '{from_variable}' following '{relationship_types}' at depth {depth}

Actual Results:
- Result Count: {result_count}
- Sample Data: {self._format_sample_data(result_data)}

Judge whether this GRAPHWALK command actually accomplished its goal by examining the ACTUAL DATA:
1. Did it find connected nodes through graph traversal?
2. Are the results different from the starting nodes?
3. Did it follow the specified relationship types and depth?
4. Does the data structure match what was requested?

Answer with JSON:
{{
  "valid": true/false,
  "reason": "explanation of why it succeeded or failed based on actual data",
  "issues": ["list of specific problems if any"],
  "confidence": 0.0-1.0
}}"""
        
        return self._get_llm_judgment(prompt)

    def validate_graphwalk_semantics(
        self,
        args: Dict[str, Any],
        source_nodes: Any,
        result_data: Any,
        result_count: int,
        contract: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Dedicated large-model validator for path semantics on GRAPHWALK results."""
        from_variable = args.get("from_variable", "")
        relationship_types = args.get("relationship_types", "")
        depth = args.get("depth", "1")
        prompt = f"""You are judging GRAPHWALK path semantics.

Goal:
- walk from source variable '{from_variable}'
- follow relationship filter '{relationship_types}'
- depth {depth}

Source sample:
{self._format_path_sample(source_nodes)}

Walk result sample:
{self._format_path_sample(result_data)}

Current contract:
{contract or {}}

Judge the traversal semantically, not just structurally:
1. Are result rows anchored to the declared source set?
2. Do the returned rows appear to respect the requested relation semantics?
3. Is the depth semantics plausible?
4. Is the output safe for downstream aggregation, or only for display/inspection?
5. What payload/grain should downstream commands treat this as?

Return strict JSON:
{{
  "semantically_valid": true,
  "reason": "short reason",
  "anchor_strength": 0.0,
  "relation_match_strength": 0.0,
  "depth_match_strength": 0.0,
  "recommended_payload_kind": "walk_rows|edge_rows|path_rows|node_rows",
  "recommended_grain": "edge|path|node|chunk|paper",
  "downstream_safe_for": ["PROCESS", "SHOW", "SELECT"],
  "repair_hint": "short hint",
  "confidence": 0.0
}}"""
        try:
            llm = self._llm_for_path_semantics()
            response = llm.call(prompt)
            return json.loads(self._extract_json(response))
        except Exception as e:
            return {
                "semantically_valid": True,
                "reason": f"path semantics validation failed: {e}",
                "anchor_strength": 0.5,
                "relation_match_strength": 0.5,
                "depth_match_strength": 0.5,
                "recommended_payload_kind": (contract or {}).get("payload_kind", "walk_rows"),
                "recommended_grain": (contract or {}).get("grain_type", "edge"),
                "downstream_safe_for": (contract or {}).get("usable_by", ["PROCESS", "SHOW", "SELECT"]),
                "repair_hint": "",
                "confidence": 0.5,
            }
    
    def _get_llm_judgment(self, prompt: str) -> Dict[str, Any]:
        """Get LLM judgment on command success."""
        try:
            response = self.llm_func.call(prompt)
            return json.loads(self._extract_json(response))
        except Exception as e:
            return {
                "valid": True,  # Default to valid if LLM fails
                "reason": f"LLM validation failed: {e}",
                "issues": [],
                "confidence": 0.5
            }
    
    def _format_sample_data(self, data: Any) -> str:
        """Format sample data for LLM validation."""
        if not data:
            return "No data"
        
        if isinstance(data, list):
            if len(data) == 0:
                return "Empty list"
            # Show first 3 items
            sample = data[:3]
            return f"List with {len(data)} items, sample: {sample}"
        elif isinstance(data, dict):
            return f"Dict with keys: {list(data.keys())}"
        else:
            return str(data)[:200]  # Truncate long strings

    def _format_path_sample(self, data: Any) -> str:
        if not data:
            return "No data"
        rows = data if isinstance(data, list) else [data]
        sample = [self._flatten_row(row) for row in rows[:6]]
        return json.dumps(sample, ensure_ascii=True)

    def _flatten_row(self, item: Any, prefix: str = "", depth: int = 0, max_depth: int = 2) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        if depth > max_depth:
            return flat
        if isinstance(item, dict):
            for key, value in item.items():
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, (str, int, float, bool)):
                    flat[next_prefix] = value
                elif isinstance(value, dict):
                    flat.update(self._flatten_row(value, next_prefix, depth + 1, max_depth))
        return flat

    @staticmethod
    def _extract_json(text: str) -> str:
        s = (text or "").strip()
        if s.startswith("```"):
            lines = s.splitlines()
            body = []
            in_fence = False
            for line in lines:
                if line.strip().startswith("```"):
                    if in_fence:
                        break
                    in_fence = True
                    continue
                if in_fence:
                    body.append(line)
            if body:
                s = "\n".join(body).strip()
        if s and s[0] not in "{[":
            starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
            if starts:
                s = s[min(starts):]
        return s
