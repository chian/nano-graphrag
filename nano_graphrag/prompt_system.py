"""
Query-aware prompt system for nano-graphrag.
Replaces the static PROMPTS dictionary with dynamic, query-optimized prompts.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Template
import re


class QueryAwarePromptSystem:
    """Dynamic prompt system that optimizes prompts based on user queries."""
    
    def __init__(self, prompts_dir: str = "prompts", llm_func=None):
        self.prompts_dir = Path(prompts_dir)
        self.llm_func = llm_func
        self._prompt_cache = {}
        self._optimized_cache = {}
        
        # Load static prompts that don't need optimization
        self._load_static_prompts()
    
    def _load_static_prompts(self):
        """Load prompts that don't need query optimization."""
        self._static_prompts = {
            "DEFAULT_ENTITY_TYPES": ["organization", "person", "geo", "event"],
            "DEFAULT_TUPLE_DELIMITER": "<|>",
            "DEFAULT_RECORD_DELIMITER": "##",
            "DEFAULT_COMPLETION_DELIMITER": "<|COMPLETE|>",
            "fail_response": "Sorry, I'm not able to provide an answer to that question.",
            "process_tickers": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
            "default_text_separator": [
                # Paragraph separators
                "\n\n",
                "\r\n\r\n",
                # Line breaks
                "\n",
                "\r\n",
                # Sentence ending punctuation
                "。",  # Chinese period
                "．",  # Full-width dot
                ".",  # English period
                "！",  # Chinese exclamation mark
                "!",  # English exclamation mark
                "？",  # Chinese question mark
                "?",  # English question mark
                # Whitespace characters
                " ",  # Space
                "\t",  # Tab
                "\u3000",  # Full-width space
                # Special characters
                "\u200b",  # Zero-width space (used in some Asian languages)
            ]
        }
    
    def _load_prompt(self, prompt_name: str) -> str:
        """Load a prompt from file."""
        if prompt_name in self._prompt_cache:
            return self._prompt_cache[prompt_name]
        
        prompt_path = self.prompts_dir / f"{prompt_name}.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self._prompt_cache[prompt_name] = content
        return content
    
    def _extract_nested_prompts(self, main_prompt: str) -> list:
        """Extract nested prompt names from main prompt using {placeholder} syntax."""
        # Only look for explicit prompt references, not template variables
        # Template variables should use <variable> syntax, not {variable} syntax
        pattern = r'\{([^}]+)\}'
        matches = re.findall(pattern, main_prompt)
        
        # Only include placeholders that are explicitly known prompt names
        # This avoids matching template variables that should be filled by the calling code
        known_prompts = {
            'entity_extraction', 'claim_extraction', 'community_report',
            'summarize_entity_descriptions', 'local_rag_response', 
            'global_map_rag_points', 'global_reduce_rag_response', 'naive_rag_response'
        }
        
        # Only return matches that are explicitly known prompt names
        return [match for match in matches if match in known_prompts]
    
    def _compose_prompt(self, main_prompt: str, user_query: str = None) -> str:
        """Compose a prompt by auto-discovering nested prompts."""
        # Extract nested prompt names
        nested_prompts = self._extract_nested_prompts(main_prompt)
        
        # Load each nested prompt
        loaded_prompts = {}
        for prompt_name in nested_prompts:
            loaded_prompts[prompt_name] = self._load_prompt(prompt_name)
        
        # Convert {variable} syntax to {{variable}} for Jinja2
        jinja_prompt = main_prompt
        for prompt_name in nested_prompts:
            jinja_prompt = jinja_prompt.replace(f"{{{prompt_name}}}", f"{{{{{prompt_name}}}}}")
        if user_query:
            jinja_prompt = jinja_prompt.replace("{user_query}", "{{user_query}}")
        
        # Create template and render
        template = Template(jinja_prompt)
        final_prompt = template.render(
            user_query=user_query or "",
            **loaded_prompts
        )
        
        return final_prompt
    
    def _optimize_prompt_with_llm(self, base_prompt: str, user_query: str) -> str:
        """Use LLM to optimize a prompt for a specific query."""
        if not self.llm_func:
            return base_prompt
        
        # Create optimization prompt
        optimizer_prompt = self._load_prompt("entity_extraction_optimizer")
        composed_optimizer = self._compose_prompt(optimizer_prompt, user_query)
        
        # Call LLM to optimize
        try:
            optimized = self.llm_func.call(composed_optimizer)
            return optimized
        except Exception as e:
            print(f"Warning: LLM optimization failed: {e}")
            return base_prompt
    
    def get_prompt(self, prompt_name: str, user_query: str = None, optimize: bool = True) -> str:
        """Get a prompt, optionally optimized for the user query."""
        
        # Return static prompts as-is
        if prompt_name in self._static_prompts:
            return self._static_prompts[prompt_name]
        
        # Check cache first
        cache_key = f"{prompt_name}_{user_query}_{optimize}"
        if cache_key in self._optimized_cache:
            return self._optimized_cache[cache_key]
        
        # Try to load as file-based prompt
        try:
            base_prompt = self._load_prompt(prompt_name)
        except FileNotFoundError:
            # If not a file-based prompt, return empty string or raise error
            raise KeyError(f"Prompt '{prompt_name}' not found in static prompts or files")
        
        # For prompts that contain JSON examples, use simple string formatting
        # instead of Jinja2 to avoid template syntax conflicts
        if prompt_name in ['plan_generation', 'completion_validator', 'process_batch', 'classify_batch']:
            final_prompt = base_prompt
        else:
            # Compose with nested prompts for other prompts
            composed_prompt = self._compose_prompt(base_prompt, user_query)
            
            # Optimize if requested and LLM is available
            if optimize and user_query and self.llm_func:
                final_prompt = self._optimize_prompt_with_llm(composed_prompt, user_query)
            else:
                final_prompt = composed_prompt
        
        # Cache the result
        self._optimized_cache[cache_key] = final_prompt
        
        return final_prompt
    
    def __getitem__(self, key: str) -> str:
        """Allow dictionary-style access for backward compatibility."""
        return self.get_prompt(key)
    
    def __setitem__(self, key: str, value: Any):
        """Allow dictionary-style assignment for backward compatibility."""
        self._static_prompts[key] = value


# Global instance for backward compatibility
_prompt_system = None

def get_prompt_system() -> QueryAwarePromptSystem:
    """Get the global prompt system instance."""
    global _prompt_system
    if _prompt_system is None:
        _prompt_system = QueryAwarePromptSystem()
    return _prompt_system

def set_prompt_system(prompt_system: QueryAwarePromptSystem):
    """Set the global prompt system instance."""
    global _prompt_system
    _prompt_system = prompt_system

# Backward compatibility - replace PROMPTS dictionary
class PROMPTS:
    """Backward compatibility wrapper for the old PROMPTS dictionary."""
    
    def __getitem__(self, key: str) -> Any:
        return get_prompt_system()[key]
    
    def __setitem__(self, key: str, value: Any):
        get_prompt_system()[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, FileNotFoundError):
            return default

# Create instance for backward compatibility
PROMPTS = PROMPTS()
