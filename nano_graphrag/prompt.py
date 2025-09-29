"""
Reference:
 - Prompts are from [graphrag](https://github.com/microsoft/graphrag)
 - Now uses QueryAwarePromptSystem for dynamic prompt optimization
"""

from .prompt_system import PROMPTS

GRAPH_FIELD_SEP = "<SEP>"

# All prompts are now loaded from the prompts/ directory via QueryAwarePromptSystem
# The PROMPTS object provides backward compatibility while enabling query-aware optimization