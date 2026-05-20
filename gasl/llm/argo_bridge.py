"""
Argo Bridge LLM wrapper for GASL system.
"""

import os
import json
import asyncio
from typing import Any, Dict, List, Optional
import httpx
from openai import AsyncOpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from ..errors import LLMError
from .runtime_config import resolve_runtime_llm_config
# `nano_graphrag.prompt_system` is imported lazily (see prompt_system property
# below) — pulling it eagerly here drags in the entire nano_graphrag dep tree
# (transformers, hnswlib, neo4j, etc.) which the RAG-only callers don't need.


class ArgoBridgeLLM:
    """Wrapper around existing argo_bridge_llm function."""
    
    def __init__(self, model: str = None, temperature: float = 0.0, max_tokens: int = 4000,
                 api_key: Optional[str] = None, base_url: Optional[str] = None,
                 reasoning_effort: Optional[str] = None):
        self.model = model or os.getenv("LLM_MODEL", "gpt41")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._transport = os.getenv("NANOGRAPHRAG_LLM_TRANSPORT", "direct").strip().lower()
        self._shim_user = os.getenv("NANOGRAPHRAG_SHIM_USER", "chia")

        runtime_cfg = resolve_runtime_llm_config(
            explicit_api_key=api_key if api_key is not None else os.getenv("LLM_API_KEY"),
            explicit_base_url=base_url or os.getenv("LLM_ENDPOINT"),
            explicit_model=self.model,
        )
        if runtime_cfg.model:
            self.model = runtime_cfg.model
        client_kwargs = {
            "api_key": runtime_cfg.api_key or "",
            "base_url": runtime_cfg.base_url or "https://apps-dev.inside.anl.gov/argoapi/v1",
        }
        if self._transport == "shim":
            client_kwargs["default_headers"] = {
                **client_kwargs.get("default_headers", {}),
                "x-api-key": client_kwargs.get("api_key", ""),
            }
        # Store credentials for creating fresh clients per call_async invocation.
        # A single AsyncOpenAI instance cannot be reused across multiple asyncio.run()
        # calls (each creates a new event loop), which causes [Errno 32] Broken Pipe.
        self._client_kwargs = client_kwargs
        self.client = AsyncOpenAI(**client_kwargs)  # kept for any direct external use

        # prompt_system is lazy — only constructed on first access via the
        # property below. Saves an expensive import for the RAG-only path.
        self._prompt_system = None

        # Per-instance token usage accumulator across all .call() invocations.
        # Server can read this after a query to report cost to the UI.
        self.usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

        # reasoning_effort: "low" | "medium" | "high" — only sent for reasoning models
        self.reasoning_effort: Optional[str] = reasoning_effort

        # Control debug output
        self.debug = os.getenv("LLM_DEBUG", "false").lower() == "true"

        # Optional streaming callback: callable(token: str) -> None
        # When set, call() streams tokens via this function AND returns the full text.
        self.stream_callback: Optional[callable] = None

    @property
    def prompt_system(self):
        if self._prompt_system is None:
            from nano_graphrag.prompt_system import QueryAwarePromptSystem
            self._prompt_system = QueryAwarePromptSystem()
        return self._prompt_system

    def _is_reasoning_model(self) -> bool:
        """Models that reject custom temperature / require defaults.

        o-series are reasoning models; some GPT-5 variants behave the same way:
          - gpt-5 / gpt-5-mini / gpt-5-nano (the "reasoning" base line)
          - gpt-5.5 family (current flagship reasoning)
          - any *-chat-latest alias (points at the current ChatGPT default,
            which is a reasoning model)
        Whereas gpt-5.4, gpt-5.2, gpt-5.1 are non-reasoning and DO accept custom
        temperature, so we only return True for the specific patterns above."""
        m = (self.model or "").lower()
        if m.startswith(("o1", "o3", "o4", "o5")):
            return True
        if "rosalind" in m:
            return True
        # Hyphenated public names (gpt-5, gpt-5-mini, ...) and Argo internal IDs
        # (gpt5, gpt5mini, gpt5nano) — all three are reasoning baseline models
        if m in ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt5", "gpt5mini", "gpt5nano"):
            return True
        # gpt-5.5 / gpt55 are reasoning flagship models
        if m.startswith("gpt-5.5") or m.startswith("gpt55"):
            return True
        if "chat-latest" in m:
            return True
        return False

    def _uses_max_completion_tokens(self) -> bool:
        """GPT-5 family and o-series reject max_tokens; need max_completion_tokens.
        GPT-4.x and earlier still take max_tokens."""
        m = (self.model or "").lower()
        return self._is_reasoning_model() or m.startswith("gpt-5") or m.startswith("gpt5")

    def _build_create_kwargs(self, prompt: str, *, stream: bool) -> dict:
        kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._transport == "shim":
            kwargs["user"] = self._shim_user
        if stream:
            kwargs["stream"] = True
        # token cap: reasoning models include reasoning tokens in this budget,
        # so give them more headroom.
        token_cap = self.max_tokens
        if self._is_reasoning_model() and token_cap < 8000:
            token_cap = 8000
        if self._uses_max_completion_tokens():
            kwargs["max_completion_tokens"] = token_cap
        else:
            kwargs["max_tokens"] = token_cap
        # reasoning models reject custom temperature (must be default 1.0)
        if not self._is_reasoning_model():
            kwargs["temperature"] = self.temperature
        # reasoning_effort is only valid for reasoning models
        if self._is_reasoning_model() and self.reasoning_effort in ("low", "medium", "high"):
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

    def clone(
        self,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> "ArgoBridgeLLM":
        """Create a new client with the same credentials but different task-level defaults."""
        return ArgoBridgeLLM(
            model=model or self.model,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            api_key=self._client_kwargs.get("api_key"),
            base_url=self._client_kwargs.get("base_url"),
            reasoning_effort=self.reasoning_effort if reasoning_effort is None else reasoning_effort,
        )

    async def call_async(self, prompt: str) -> str:
        """Make async LLM call, streaming tokens if stream_callback is set."""
        if self.debug:
            print(f"DEBUG: LLM PROMPT SENT:\n{prompt}\n")
            print("="*80)
        try:
            if self._transport == "shim":
                payload = self._build_create_kwargs(prompt, stream=False)
                async with httpx.AsyncClient(
                    headers={"x-api-key": self._client_kwargs.get("api_key", "")},
                    timeout=300.0,
                ) as client:
                    response = await client.post(
                        self._client_kwargs["base_url"].rstrip("/") + "/chat/completions",
                        json=payload,
                    )
                if response.status_code == 401:
                    raise LLMError(
                        f"LLM call failed: Unauthorized: {response.text}",
                        "argo_bridge",
                        self.model,
                        category="auth",
                        status_code=401,
                        original_type="AuthError",
                        fatal=True,
                    )
                if response.status_code >= 400:
                    raise LLMError(
                        f"LLM call failed: {response.status_code}: {response.text}",
                        "argo_bridge",
                        self.model,
                        category="endpoint" if response.status_code >= 500 else "request",
                        status_code=response.status_code,
                        original_type="HTTPStatusError",
                        fatal=response.status_code >= 500,
                    )
                body = response.json()
                result = (((body.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
                usage = body.get("usage") or {}
                self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0) or 0
                self.usage["completion_tokens"] += usage.get("completion_tokens", 0) or 0
                self.usage["total_tokens"] += usage.get("total_tokens", 0) or 0
                self.usage["calls"] += 1
                return result
            # Create a fresh client bound to the current event loop.
            # Reusing self.client across asyncio.run() calls (each spawns a new
            # loop) causes [Errno 32] Broken Pipe on the underlying HTTP transport.
            async with AsyncOpenAI(**self._client_kwargs) as client:
                if self.stream_callback is not None:
                    # Streaming path
                    kwargs = self._build_create_kwargs(prompt, stream=True)
                    stream = await client.chat.completions.create(**kwargs)
                    full_text = ""
                    async for chunk in stream:
                        token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                        if token:
                            full_text += token
                            try:
                                self.stream_callback(token)
                            except Exception:
                                pass
                    if self.debug:
                        print(f"DEBUG: LLM RESPONSE (streamed):\n{full_text}\n")
                        print("="*80)
                    return full_text
                else:
                    # Non-streaming path (original behaviour)
                    kwargs = self._build_create_kwargs(prompt, stream=False)
                    response = await client.chat.completions.create(**kwargs)
                    result = response.choices[0].message.content
                    # Accumulate usage across calls (non-streaming exposes it directly).
                    u = getattr(response, "usage", None)
                    if u is not None:
                        self.usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
                        self.usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
                        self.usage["total_tokens"] += getattr(u, "total_tokens", 0) or 0
                    self.usage["calls"] += 1
                    if self.debug:
                        print(f"DEBUG: LLM RESPONSE RECEIVED:\n{result}\n")
                        print("="*80)
                    return result
        except AuthenticationError as e:
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="auth",
                status_code=getattr(e, "status_code", None),
                original_type=type(e).__name__,
                fatal=True,
            )
        except PermissionDeniedError as e:
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="auth",
                status_code=getattr(e, "status_code", None),
                original_type=type(e).__name__,
                fatal=True,
            )
        except (APIConnectionError, APITimeoutError) as e:
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="endpoint",
                status_code=getattr(e, "status_code", None),
                original_type=type(e).__name__,
                fatal=True,
            )
        except (RateLimitError, InternalServerError) as e:
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="endpoint",
                status_code=getattr(e, "status_code", None),
                original_type=type(e).__name__,
                fatal=True,
            )
        except APIStatusError as e:
            code = getattr(e, "status_code", None)
            fatal = code is not None and code >= 500
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="endpoint" if fatal else "request",
                status_code=code,
                original_type=type(e).__name__,
                fatal=fatal,
            )
        except (BadRequestError, UnprocessableEntityError, ContentFilterFinishReasonError) as e:
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="request",
                status_code=getattr(e, "status_code", None),
                original_type=type(e).__name__,
                fatal=False,
            )
        except Exception as e:
            raise LLMError(
                f"LLM call failed: {e}",
                "argo_bridge",
                self.model,
                category="unknown",
                status_code=getattr(e, "status_code", None),
                original_type=type(e).__name__,
                fatal=False,
            )

    def call(self, prompt: str) -> str:
        """Make synchronous LLM call (streams if stream_callback is set)."""
        try:
            # Check if we're in an async context
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.call_async(prompt))
                result = future.result()
                return result
        except RuntimeError:
            # No event loop running, create new one
            result = asyncio.run(self.call_async(prompt))
            return result
    
    def create_plan_prompt(self, query: str, schema: Dict[str, Any], 
                          state: Dict[str, Any], history: list) -> str:
        """Create prompt for LLM to generate a plan using centralized prompt system."""
        # Get the base prompt from the centralized system with query optimization
        base_prompt = self.prompt_system.get_prompt("plan_generation", user_query=query, optimize=True)
        
        strategy_insights = state.get("strategy_insights", "")
        
        # Format the prompt with the current context
        formatted_prompt = base_prompt.format(
            query=query,
            hint_text=(
                f"\n\nPrevious repair constraints:\n{strategy_insights}" if strategy_insights else ""
            ),
            node_labels=schema.get('node_labels', []),
            edge_types=schema.get('edge_types', []),
            node_properties=schema.get('node_properties', []),
            edge_properties=schema.get('edge_properties', []),
            state_variables=self._format_state(state.get("variables", {})),
            execution_history=self._format_history(history),
            produced_artifacts=self._format_produced_artifacts(state.get("produced_artifacts", [])),
        )
        
        return formatted_prompt

    def create_plan_iteration_prompt(
        self,
        query: str,
        previous_plan: Dict[str, Any],
        results: Dict[str, Any],
        iteration: int,
        state: Dict[str, Any],
    ) -> str:
        """Create prompt for the next planning iteration, optionally patching the previous plan."""
        base_prompt = self.prompt_system.get_prompt("plan_repair")
        return base_prompt.format(
            query=query,
            previous_plan=json.dumps(previous_plan, indent=2),
            results=self._format_results(results),
            iteration=iteration,
            execution_history=self._format_history(state.get("history", [])),
            produced_artifacts=self._format_produced_artifacts(state.get("produced_artifacts", [])),
            strategy_insights=state.get("strategy_insights", ""),
            failure_summary=json.dumps(state.get("last_failure_summary", {}), indent=2),
        )

    def create_plan_repair_prompt(
        self,
        query: str,
        previous_plan: Dict[str, Any],
        results: Dict[str, Any],
        iteration: int,
        state: Dict[str, Any],
    ) -> str:
        """Backward-compatible alias."""
        return self.create_plan_iteration_prompt(
            query=query,
            previous_plan=previous_plan,
            results=results,
            iteration=iteration,
            state=state,
        )
    
    def create_analysis_prompt(self, query: str, results: Dict[str, Any]) -> str:
        """Create prompt for final analysis."""
        # Get the prompt from the centralized system
        base_prompt = self.prompt_system.get_prompt("final_analysis")
        
        # Format the prompt with the current context
        formatted_prompt = base_prompt.format(
            query=query,
            results=self._format_results(results)
        )
        
        return formatted_prompt
    
    def create_strategy_adaptation_prompt(self, query: str, results: Dict[str, Any], iteration: int, schema: Dict[str, Any], state: Dict[str, Any]) -> str:
        """Create prompt for strategy adaptation between iterations."""
        # Get the prompt from the centralized system
        base_prompt = self.prompt_system.get_prompt("strategy_adaptation")
        
        execution_history = state.get("execution_history", "")
        
        # Format the prompt with the current context
        prompt = base_prompt.format(
            query=query,
            iteration=iteration,
            results=self._format_results(results),
            execution_history=execution_history,
            node_labels=schema.get('node_labels', []),
            edge_types=schema.get('edge_types', []),
            node_properties=schema.get('node_properties', []),
            edge_properties=schema.get('edge_properties', [])
        )
        return prompt
    
    def _format_state(self, state: Dict[str, Any]) -> str:
        """Format state for prompt."""
        if not state:
            return "No state variables defined yet.\n\nIMPORTANT: You must DECLARE state variables first before doing any meaningful work. Use DECLARE commands to create the data structures you need based on the query. For example:\n- DECLARE country_analysis AS DICT WITH_DESCRIPTION \"Analysis results for countries\"\n- DECLARE country_list AS LIST WITH_DESCRIPTION \"List of countries found\"\n- DECLARE country_count AS COUNTER WITH_DESCRIPTION \"Count of countries meeting criteria\""
        
        formatted = []
        for key, value in state.items():
            if isinstance(value, dict) and "_meta" in value:
                var_type = value["_meta"].get("type", "unknown")
                description = value["_meta"].get("description", "")
                if var_type == "LIST":
                    count = len(value.get("items", []))
                    formatted.append(f"- {key} ({var_type}): {count} items - {description}")
                    
                    # Show available fields for LIST variables (schema only - no actual data)
                    items = value.get("items", [])
                    if items and isinstance(items, list) and len(items) > 0:
                        # Analyze first few items to determine available fields
                        sample_fields = self._analyze_item_fields(items[:3])
                        if sample_fields:
                            formatted.append(f"  🔍 AVAILABLE FIELDS (use these exact names in commands):")
                            for field_name, field_type in sample_fields.items():
                                formatted.append(f"    - {field_name}: {field_type}")
                        else:
                            # Fallback to standard graph entity schema
                            formatted.append(f"  🔍 AVAILABLE FIELDS (use these exact names in commands):")
                            formatted.append(f"    - entity_type: string")
                            formatted.append(f"    - description: string")
                            formatted.append(f"    - source_id: string")
                            formatted.append(f"    - clusters: string")
                    else:
                        # If no items, show standard graph entity schema
                        formatted.append(f"  🔍 AVAILABLE FIELDS (use these exact names in commands):")
                        formatted.append(f"    - entity_type: string")
                        formatted.append(f"    - description: string")
                        formatted.append(f"    - source_id: string")
                        formatted.append(f"    - clusters: string")
                                
                elif var_type == "DICT":
                    keys = [k for k in value.keys() if k != "_meta"]
                    formatted.append(f"- {key} ({var_type}): {len(keys)} keys - {description}")
                elif var_type == "COUNTER":
                    count = value.get("value", 0)
                    formatted.append(f"- {key} ({var_type}): {count} - {description}")
            else:
                # For non-GASL variables, show only type and count, not actual data
                if isinstance(value, list):
                    formatted.append(f"- {key} (list): {len(value)} items")
                elif isinstance(value, dict):
                    formatted.append(f"- {key} (dict): {len(value)} keys")
                else:
                    formatted.append(f"- {key}: {type(value).__name__}")
        
        return "\n".join(formatted)
    
    def _analyze_item_fields(self, items: List[Dict]) -> Dict[str, str]:
        """Analyze sample items to determine available fields and their types."""
        if not items:
            return {}
        
        field_types = {}
        for item in items:
            if isinstance(item, dict):
                for field_name, field_value in item.items():
                    if field_name == "_meta":
                        continue
                    
                    # Determine field type
                    if isinstance(field_value, bool):
                        field_type = "boolean"
                    elif isinstance(field_value, (int, float)):
                        field_type = "number"
                    elif isinstance(field_value, str):
                        field_type = "string"
                    elif field_value is None:
                        field_type = "null"
                    else:
                        field_type = "unknown"
                    
                    # Store the most specific type we've seen for this field
                    if field_name not in field_types or field_type != "unknown":
                        field_types[field_name] = field_type
        
        return field_types
    
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

    def _format_produced_artifacts(self, artifacts: list) -> str:
        """Format recently produced artifacts for prompt context."""
        if not artifacts:
            return "No produced artifacts yet."
        formatted = []
        for art in artifacts[-8:]:
            parts = [
                f"- {art.get('variable','')}: {art.get('command_type','')} -> {art.get('payload_kind','')}"
                f" ({art.get('item_count',0)} items)"
            ]
            if art.get("label_field"):
                parts.append(f"label={art.get('label_field')}")
            if art.get("metric_field"):
                parts.append(f"metric={art.get('metric_field')}")
            if art.get("grain_type"):
                parts.append(f"grain={art.get('grain_type')}")
            if art.get("row_schema"):
                parts.append(f"fields={art.get('row_schema', [])[:8]}")
            if art.get("safe_for"):
                parts.append(f"safe_for={art.get('safe_for')}")
            if art.get("refinement_hint"):
                parts.append(f"refinement_hint={art.get('refinement_hint')}")
            if art.get("refinement_reason"):
                parts.append(f"refinement_note={art.get('refinement_reason')}")
            formatted.append(", ".join(parts))
        return "\n".join(formatted)
    
    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format results for prompt."""
        formatted = []
        for key, value in results.items():
            if isinstance(value, list):
                formatted.append(f"{key}: {len(value)} items")
                # Show all items
                for i, item in enumerate(value):
                    formatted.append(f"  {i+1}. {item}")
            else:
                formatted.append(f"{key}: {value}")
        
        return "\n".join(formatted)
