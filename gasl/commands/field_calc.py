"""
Field Calculation command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class FieldCalcHandler(CommandHandler):
    """Handles field calculation commands: CALCULATE, SCORE, RANK, WEIGHT."""
    
    def __init__(self, state_store, context_store, llm_func=None):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["CALCULATE", "SCORE", "RANK", "WEIGHT"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute field calculation command."""
        try:
            if command.command_type == "CALCULATE":
                return self._execute_calculate(command)
            elif command.command_type == "SCORE":
                return self._execute_score(command)
            elif command.command_type == "RANK":
                return self._execute_rank(command)
            elif command.command_type == "WEIGHT":
                return self._execute_weight(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown field calculation command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_calculate(self, command: Command) -> ExecutionResult:
        """Execute CALCULATE command."""
        args = command.args
        variable = args["variable"]
        field_name = args["field_name"]
        computation = args["computation"]
        
        print(f"DEBUG: CALCULATE - variable: {variable}, field: {field_name}, computation: {computation}")
        
        # Get data to calculate on
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform calculation based on computation type
        calculated_data = []
        for item in data:
            new_item = {**item}  # Copy original item
            
            # Simple built-in calculations
            if computation == "item_count":
                new_item[field_name] = 1
            elif computation == "id_length":
                new_item[field_name] = len(str(item.get("id", "")))
            elif computation == "description_length":
                new_item[field_name] = len(str(item.get("description", "")))
            elif computation.startswith("count_"):
                # Count occurrences of a field value
                field_to_count = computation.replace("count_", "")
                field_value = item.get(field_to_count)
                new_item[field_name] = 1 if field_value else 0
            elif self.llm_func and "based on" in computation:
                # Use LLM for complex calculations
                calc_result = self._llm_calculate(item, field_name, computation)
                new_item[field_name] = calc_result
            else:
                # Default calculation
                new_item[field_name] = 0
            
            calculated_data.append(new_item)
        
        # Update the state variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = calculated_data
                self.state_store._save_state()
        
        print(f"DEBUG: CALCULATE - added field '{field_name}' to {len(calculated_data)} items")
        
        return self._create_result(
            command=command,
            status="success",
            data=calculated_data,
            count=len(calculated_data),
            provenance=[self._create_provenance("calculate", "calculate",
                                               variable=variable, field_name=field_name, computation=computation)]
        )
    
    def _execute_score(self, command: Command) -> ExecutionResult:
        """Execute SCORE command using LLM."""
        args = command.args
        variable = args["variable"]
        scoring_criteria = args["scoring_criteria"]
        
        print(f"DEBUG: SCORE - variable: {variable}, criteria: {scoring_criteria}")
        
        # Get data to score
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for SCORE command")
        
        # Create prompt for LLM scoring
        prompt = self._create_score_prompt(data, scoring_criteria)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: SCORE - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            score_result = json.loads(llm_response)
            scored_items = score_result.get("scored_items", [])
            
            # Update items with scores
            scored_data = []
            for item in data:
                new_item = {**item}
                # Find matching score
                for scored_item in scored_items:
                    if scored_item.get("id") == item.get("id"):
                        new_item["score"] = scored_item.get("score", 0)
                        new_item["score_reason"] = scored_item.get("reason", "")
                        break
                else:
                    new_item["score"] = 0
                    new_item["score_reason"] = "No score assigned"
                scored_data.append(new_item)
            
            # Update the state variable
            if self.state_store.has_variable(variable):
                var_data = self.state_store.get_variable(variable)
                if isinstance(var_data, dict) and "items" in var_data:
                    var_data["items"] = scored_data
                    self.state_store._save_state()
            
            print(f"DEBUG: SCORE - scored {len(scored_data)} items")
            
            return self._create_result(
                command=command,
                status="success",
                data=scored_data,
                count=len(scored_data),
                provenance=[self._create_provenance("score", "score",
                                                   variable=variable, scoring_criteria=scoring_criteria)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM scoring response as JSON")
    
    def _execute_rank(self, command: Command) -> ExecutionResult:
        """Execute RANK command."""
        args = command.args
        variable = args["variable"]
        rank_field = args["rank_field"]
        order = args.get("order", "desc")  # desc or asc
        
        print(f"DEBUG: RANK - variable: {variable}, field: {rank_field}, order: {order}")
        
        # Get data to rank
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Sort data by rank field
        try:
            sorted_data = sorted(data, 
                               key=lambda x: self._get_numeric_value(x, rank_field),
                               reverse=(order == "desc"))
        except Exception as e:
            return self._create_result(command=command, status="error",
                                     error_message=f"Failed to sort by field {rank_field}: {str(e)}")
        
        # Add rank field
        ranked_data = []
        for i, item in enumerate(sorted_data):
            new_item = {**item}
            new_item["rank"] = i + 1
            ranked_data.append(new_item)
        
        # Update the state variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = ranked_data
                self.state_store._save_state()
        
        print(f"DEBUG: RANK - ranked {len(ranked_data)} items by {rank_field}")
        
        return self._create_result(
            command=command,
            status="success",
            data=ranked_data,
            count=len(ranked_data),
            provenance=[self._create_provenance("rank", "rank",
                                               variable=variable, rank_field=rank_field, order=order)]
        )
    
    def _execute_weight(self, command: Command) -> ExecutionResult:
        """Execute WEIGHT command using LLM."""
        args = command.args
        variable = args["variable"]
        weighting_criteria = args["weighting_criteria"]
        
        print(f"DEBUG: WEIGHT - variable: {variable}, criteria: {weighting_criteria}")
        
        # Get data to weight
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for WEIGHT command")
        
        # Create prompt for LLM weighting
        prompt = self._create_weight_prompt(data, weighting_criteria)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: WEIGHT - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            weight_result = json.loads(llm_response)
            weighted_items = weight_result.get("weighted_items", [])
            
            # Update items with weights
            weighted_data = []
            for item in data:
                new_item = {**item}
                # Find matching weight
                for weighted_item in weighted_items:
                    if weighted_item.get("id") == item.get("id"):
                        new_item["weight"] = weighted_item.get("weight", 1.0)
                        new_item["weight_reason"] = weighted_item.get("reason", "")
                        break
                else:
                    new_item["weight"] = 1.0
                    new_item["weight_reason"] = "Default weight"
                weighted_data.append(new_item)
            
            # Update the state variable
            if self.state_store.has_variable(variable):
                var_data = self.state_store.get_variable(variable)
                if isinstance(var_data, dict) and "items" in var_data:
                    var_data["items"] = weighted_data
                    self.state_store._save_state()
            
            print(f"DEBUG: WEIGHT - weighted {len(weighted_data)} items")
            
            return self._create_result(
                command=command,
                status="success",
                data=weighted_data,
                count=len(weighted_data),
                provenance=[self._create_provenance("weight", "weight",
                                                   variable=variable, weighting_criteria=weighting_criteria)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM weighting response as JSON")
    
    def _llm_calculate(self, item: Dict, field_name: str, computation: str) -> Any:
        """Use LLM for complex field calculations."""
        if not self.llm_func:
            return 0
        
        prompt = f"""Calculate the field '{field_name}' for this item based on: {computation}

Item data:
{item}

Return only the calculated value (number, string, or boolean).
"""
        
        try:
            result = self.llm_func.call(prompt)
            # Try to convert to appropriate type
            if result.isdigit():
                return int(result)
            try:
                return float(result)
            except ValueError:
                return result.strip()
        except Exception:
            return 0
    
    def _create_score_prompt(self, data: Any, scoring_criteria: str) -> str:
        """Create prompt for LLM scoring."""
        prompt = f"""Score each item according to this criteria: {scoring_criteria}

Data to score:
{self._format_data_for_llm(data)}

Instructions:
1. Score each item on a scale from 0-100 based on the criteria
2. Provide a reason for each score
3. Return your results as a JSON object with this structure:
{{
  "scored_items": [
    {{"id": "item_id", "score": 85, "reason": "why this score"}},
    ...
  ],
  "scoring_summary": {{
    "criteria_used": "{scoring_criteria}",
    "score_range": "0-100",
    "average_score": 0
  }}
}}

Be consistent in your scoring approach.
"""
        return prompt
    
    def _create_weight_prompt(self, data: Any, weighting_criteria: str) -> str:
        """Create prompt for LLM weighting."""
        prompt = f"""Assign weights to each item according to this criteria: {weighting_criteria}

Data to weight:
{self._format_data_for_llm(data)}

Instructions:
1. Assign a weight to each item (typically 0.0 to 2.0, where 1.0 is normal)
2. Higher weights indicate higher importance/relevance
3. Provide a reason for each weight
4. Return your results as a JSON object with this structure:
{{
  "weighted_items": [
    {{"id": "item_id", "weight": 1.5, "reason": "why this weight"}},
    ...
  ],
  "weighting_summary": {{
    "criteria_used": "{weighting_criteria}",
    "weight_range": "0.0-2.0",
    "average_weight": 1.0
  }}
}}

Be consistent in your weighting approach.
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
    
    def _get_numeric_value(self, item: Dict, field: str) -> float:
        """Get numeric value from item field for ranking."""
        value = item.get(field, 0)
        if isinstance(value, (int, float)):
            return float(value)
        elif isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        else:
            return 0.0
