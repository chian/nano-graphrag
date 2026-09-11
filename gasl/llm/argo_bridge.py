"""
Argo Bridge LLM wrapper for GASL system.
"""

import os
import json
import asyncio
import contextvars
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
from ..contracts import infer_row_schema
from ..provenance import WEIGHT_BASIS_UNKNOWN, basis_components, is_no_evidence
from .runtime_config import resolve_runtime_llm_config
# `nano_graphrag.prompt_system` is imported lazily (see prompt_system property
# below) — pulling it eagerly here drags in the entire nano_graphrag dep tree
# (transformers, hnswlib, neo4j, etc.) which the RAG-only callers don't need.


class ArgoBridgeLLM:
    """Wrapper around existing argo_bridge_llm function."""

    # Characters a recency-ordered prompt section may occupy. Execution history
    # and produced artifacts both grow without limit across a run, so something
    # has to bound them, and recency is a defensible ordering for both: the
    # planner is deciding what to do next.
    #
    # The bound is on MEASURED SIZE rather than on a count of entries, because a
    # count is not a budget — five verbose entries and five terse ones cost
    # wildly different amounts of the thing actually being conserved. And
    # whatever it omits is stated in the prompt, so a run failing the same way
    # for forty turns cannot look identical to a five-turn-old run.
    #
    # NO MEASUREMENT JUSTIFIES 4000. Nothing in this tree records how much
    # history a planner actually uses, and this value was chosen to be
    # comfortably larger than the sections the deleted `[-5:]` / `[-8:]` cuts
    # were producing, so that it widens rather than narrows what the planner
    # sees. It is a candidate for the first experiment that measures it.
    PROMPT_SECTION_CHAR_BUDGET = 4000

    @classmethod
    def _window_by_size(cls, lines: List[str]) -> tuple[List[str], int]:
        """Take the most recent lines that fit the character budget.

        Returns those lines in their original (chronological) order plus the
        number omitted. Selection runs newest-first so the budget is spent on
        the entries most likely to matter; the result is re-ordered for display
        because a reader cannot interpret a sequence presented backwards.
        """
        kept: List[str] = []
        used = 0
        for index, line in enumerate(reversed(lines)):
            cost = len(line) + 1
            # The newest entry is always kept, however long it is: dropping it
            # to respect the budget would leave the section describing a moment
            # that is not the current one.
            if kept and used + cost > cls.PROMPT_SECTION_CHAR_BUDGET:
                # Stop rather than skip. Continuing past an oversized entry to
                # collect older shorter ones would present the planner with a
                # section that is neither the whole history nor a contiguous
                # recent slice of it, with a hole in the middle it cannot see.
                return list(reversed(kept)), len(lines) - index
            used += cost
            kept.append(line)
        kept.reverse()
        return kept, 0

    def __init__(self, model: str = None, temperature: float = 0.0, max_tokens: int = 4000,
                 api_key: Optional[str] = None, base_url: Optional[str] = None,
                 reasoning_effort: Optional[str] = None):
        requested_model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._shim_user = os.getenv("NANOGRAPHRAG_SHIM_USER", "chia")

        runtime_cfg = resolve_runtime_llm_config(
            explicit_api_key=api_key,
            explicit_base_url=base_url or os.getenv("LLM_ENDPOINT"),
            explicit_model=requested_model,
        )
        self.model = runtime_cfg.model
        self._transport = runtime_cfg.transport
        client_kwargs = {"api_key": runtime_cfg.api_key or ""}
        if runtime_cfg.base_url:
            client_kwargs["base_url"] = runtime_cfg.base_url
        if self._transport == "shim":
            client_kwargs["default_headers"] = {
                **client_kwargs.get("default_headers", {}),
                "x-api-key": client_kwargs.get("api_key", ""),
            }
        # Store credentials for creating loop-local clients. Reusing a single
        # AsyncOpenAI instance across different event loops causes transport
        # issues, but creating a brand-new client per request causes excessive
        # DNS/connection churn under high concurrency.
        self._client_kwargs = client_kwargs
        self._sdk_retries = int(os.getenv("LLM_SDK_RETRIES", "0"))
        self._connect_timeout_sec = float(os.getenv("LLM_CONNECT_TIMEOUT_SEC", "10.0"))
        self._read_timeout_sec = float(os.getenv("LLM_READ_TIMEOUT_SEC", "300.0"))
        self._write_timeout_sec = float(os.getenv("LLM_WRITE_TIMEOUT_SEC", "300.0"))
        self._pool_timeout_sec = float(os.getenv("LLM_POOL_TIMEOUT_SEC", "30.0"))
        self._call_timeout_sec = float(
            os.getenv(
                "LLM_CALL_TIMEOUT_SEC",
                str(self._connect_timeout_sec + self._read_timeout_sec + 30.0),
            )
        )
        self._max_connections = int(os.getenv("LLM_MAX_CONNECTIONS", "128"))
        self._max_keepalive_connections = int(os.getenv("LLM_MAX_KEEPALIVE_CONNECTIONS", "64"))
        self._connection_retries = int(os.getenv("LLM_CONNECTION_RETRIES", "3"))
        self._reasoning_token_floor = int(os.getenv("LLM_REASONING_TOKEN_FLOOR", "16000"))
        self._shim_connection_retries = int(
            os.getenv("LLM_SHIM_CONNECTION_RETRIES", str(max(self._connection_retries, 60)))
        )
        self._shim_retry_max_sleep_sec = float(os.getenv("LLM_SHIM_RETRY_MAX_SLEEP_SEC", "8.0"))
        self._loop_id: Optional[int] = None
        self._loop_http_client: Optional[httpx.AsyncClient] = None
        self._loop_openai_client: Optional[AsyncOpenAI] = None
        self.client = self._create_openai_client()  # kept for any direct external use

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

    def _build_create_kwargs(
        self,
        prompt: str,
        *,
        stream: bool,
        system_prompt: Optional[str] = None,
    ) -> dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        if self._transport == "shim":
            kwargs["user"] = self._shim_user
        elif os.getenv("NANOGRAPHRAG_SEND_USER", "false").lower() == "true":
            kwargs["user"] = self._shim_user
        if stream:
            kwargs["stream"] = True
        # token cap: reasoning models include reasoning tokens in this budget,
        # so give them more headroom.
        token_cap = self.max_tokens
        if self._is_reasoning_model() and token_cap < self._reasoning_token_floor:
            token_cap = self._reasoning_token_floor
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

    def _create_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=self._connect_timeout_sec,
                read=self._read_timeout_sec,
                write=self._write_timeout_sec,
                pool=self._pool_timeout_sec,
            ),
            limits=httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive_connections,
                keepalive_expiry=30.0,
            ),
            http2=False,
        )

    def _create_openai_client(self) -> AsyncOpenAI:
        http_client = self._create_http_client()
        return AsyncOpenAI(
            **self._client_kwargs,
            max_retries=self._sdk_retries,
            timeout=http_client.timeout,
            http_client=http_client,
        )

    async def _reset_loop_client(self) -> None:
        if self._loop_http_client is not None:
            try:
                await self._loop_http_client.aclose()
            except Exception:
                pass
        self._loop_http_client = None
        self._loop_openai_client = None
        self._loop_id = None

    def _get_loop_openai_client(self) -> AsyncOpenAI:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        if self._loop_openai_client is None or self._loop_id != loop_id:
            self._loop_http_client = self._create_http_client()
            self._loop_openai_client = AsyncOpenAI(
                **self._client_kwargs,
                max_retries=self._sdk_retries,
                timeout=self._loop_http_client.timeout,
                http_client=self._loop_http_client,
            )
            self._loop_id = loop_id
        return self._loop_openai_client

    @staticmethod
    def _shim_response_retryable(response: httpx.Response) -> bool:
        if response.status_code in {500, 502, 503, 504}:
            return True
        return (
            response.status_code == 404
            and "DeploymentNotFound" in response.text
        )

    async def _call_direct_once(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
    ) -> str:
        client = self._get_loop_openai_client()
        if self.stream_callback is not None:
            kwargs = self._build_create_kwargs(
                prompt,
                stream=True,
                system_prompt=system_prompt,
            )
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

        kwargs = self._build_create_kwargs(
            prompt,
            stream=False,
            system_prompt=system_prompt,
        )
        response = await client.chat.completions.create(**kwargs)
        result = response.choices[0].message.content
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

    async def call_async(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Make async LLM call, streaming tokens if stream_callback is set."""
        if self.debug:
            print(f"DEBUG: LLM PROMPT SENT:\n{prompt}\n")
            print("="*80)
        try:
            if self._transport == "shim":
                payload = self._build_create_kwargs(
                    prompt,
                    stream=False,
                    system_prompt=system_prompt,
                )
                last_response: httpx.Response | None = None
                async with httpx.AsyncClient(
                    headers={"x-api-key": self._client_kwargs.get("api_key", "")},
                    timeout=httpx.Timeout(
                        connect=self._connect_timeout_sec,
                        read=self._read_timeout_sec,
                        write=self._write_timeout_sec,
                        pool=self._pool_timeout_sec,
                    ),
                ) as client:
                    for attempt in range(self._shim_connection_retries + 1):
                        response = await client.post(
                            self._client_kwargs["base_url"].rstrip("/") + "/chat/completions",
                            json=payload,
                        )
                        last_response = response
                        if not self._shim_response_retryable(response):
                            break
                        if attempt >= self._shim_connection_retries:
                            break
                        await asyncio.sleep(min(2 ** attempt, self._shim_retry_max_sleep_sec))
                response = last_response
                if response is None:
                    raise RuntimeError("LLM shim call exhausted retries without a terminal response")
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
            retryable_codes = {500, 502, 503, 504}
            last_exc: Optional[Exception] = None
            for attempt in range(self._connection_retries + 1):
                try:
                    direct_call = self._call_direct_once(
                        prompt,
                        system_prompt=system_prompt,
                    )
                    if self._call_timeout_sec > 0:
                        return await asyncio.wait_for(
                            direct_call,
                            timeout=self._call_timeout_sec,
                        )
                    return await direct_call
                except (
                    APIConnectionError,
                    APITimeoutError,
                    RateLimitError,
                    InternalServerError,
                    TimeoutError,
                ) as exc:
                    if isinstance(exc, TimeoutError) and not isinstance(exc, asyncio.TimeoutError):
                        raise
                    last_exc = exc
                    await self._reset_loop_client()
                except asyncio.CancelledError:
                    await self._reset_loop_client()
                    raise
                except APIStatusError as exc:
                    if getattr(exc, "status_code", None) not in retryable_codes:
                        raise
                    last_exc = exc
                    await self._reset_loop_client()
                if attempt >= self._connection_retries:
                    if last_exc is not None:
                        raise last_exc
                    break
                await asyncio.sleep(min(2 ** attempt, 8))
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("LLM direct call exhausted retries without a terminal response")
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
        except (APIConnectionError, APITimeoutError, asyncio.TimeoutError) as e:
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
                # Carry the caller's context across the thread hop. A bare pool
                # does not propagate contextvars, so everything the caller had
                # established -- the active cost meter, and equally the tracing
                # and logging context -- was replaced by defaults inside the
                # worker. Spend then landed on an orphan meter and surfaced only
                # as a run residual at round 0: present in the total, stripped
                # of the action and round that would let anyone attribute it.
                #
                # This is a general context-loss defect that happens to have
                # been found through cost. `contextvars` is stdlib, so gasl/
                # gains no dependency in any direction.
                ctx = contextvars.copy_context()
                future = executor.submit(ctx.run, asyncio.run, self.call_async(prompt))
                result = future.result()
                return result
        except RuntimeError:
            # No event loop running, create new one
            result = asyncio.run(self.call_async(prompt))
            return result
    
    def create_plan_prompt(
        self,
        query: str,
        schema: Dict[str, Any],
        state: Dict[str, Any],
        history: list,
        symbol_table: Optional[list[Dict[str, Any]]] = None,
        validation_defects: Optional[list[Dict[str, Any]]] = None,
    ) -> str:
        """Create prompt for LLM to generate a plan using centralized prompt system."""
        # Get the base prompt from the centralized system with query optimization
        base_prompt = self.prompt_system.get_prompt("plan_generation", user_query=query, optimize=True)
        
        planner_constraints = state.get("planner_constraints", []) or []
        symbol_table = symbol_table or []
        validation_defects = validation_defects or []
        symbol_table_guidance = ""
        if symbol_table:
            symbol_table_guidance = (
                "PLAN SYMBOL TABLE:\n"
                "- Use only the GASL variable names listed below.\n"
                "- Every consumed symbol must either already exist in state/context or be produced earlier in the command list.\n"
                "- Keep commands in standard GASL DSL strings.\n"
                f"{json.dumps(symbol_table, indent=2)}\n"
            )
            if validation_defects:
                symbol_table_guidance += (
                    "Previous static validation defects to avoid:\n"
                    f"{json.dumps(validation_defects, indent=2)}\n"
                )
        
        # Format the prompt with the current context
        formatted_prompt = base_prompt.format(
            query=query,
            hint_text=self._format_planner_constraints(planner_constraints),
            node_labels=schema.get('node_labels', []),
            edge_types=schema.get('edge_types', []),
            node_properties=schema.get('node_properties', []),
            edge_properties=schema.get('edge_properties', []),
            state_variables=self._format_state(state.get("variables", {})),
            symbol_table_guidance=symbol_table_guidance,
            execution_history=self._format_history(history),
            produced_artifacts=self._format_produced_artifacts(state.get("produced_artifacts", [])),
        )
        
        return formatted_prompt

    def create_plan_symbols_prompt(self, query: str, schema: Dict[str, Any],
                                  state: Dict[str, Any], history: list) -> str:
        """Create prompt for the first pass of two-phase planning."""
        base_prompt = self.prompt_system.get_prompt("plan_symbols")
        return base_prompt.format(
            query=query,
            node_labels=schema.get('node_labels', []),
            edge_types=schema.get('edge_types', []),
            node_properties=schema.get('node_properties', []),
            edge_properties=schema.get('edge_properties', []),
            state_variables=self._format_state(state.get("variables", {})),
            execution_history=self._format_history(history),
            produced_artifacts=self._format_produced_artifacts(state.get("produced_artifacts", [])),
        )

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
            symbol_table=json.dumps(state.get("plan_symbol_table", []) or [], indent=2),
            # Rendered, not `json.dumps`-ed. Now that constraints are typed
            # records this site would have printed raw dicts complete with
            # `authored_iteration` and `status` keys into a prompt, and it is a
            # DIFFERENT prompt from the one above -- fixing one consumer and not
            # the other leaves half the planner calls misinformed.
            planner_constraints=self._format_planner_constraints(
                state.get("planner_constraints", []) or []
            ),
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

        execution_history = self._format_history(state.get("history", []))
        failure_summary = json.dumps(state.get("last_failure_summary", {}), indent=2)
        expertise_context = json.dumps((state.get("last_failure_summary", {}) or {}).get("expertise_context", {}), indent=2)
        
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
        if failure_summary and failure_summary != "{}":
            prompt += f"\n\nCurrent Iteration Failure Summary:\n{failure_summary}"
        if expertise_context and expertise_context != "{}":
            prompt += f"\n\nExpertise Context:\n{expertise_context}"
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
                    contract = value.get("_meta", {}).get("contract", {}) if isinstance(value, dict) else {}
                    row_schema = list(contract.get("row_schema") or [])
                    if contract.get("grain_type"):
                        formatted.append(f"  🔹 GRAIN: {contract.get('grain_type')}")
                    if contract.get("grain_keys"):
                        formatted.append(f"  🔹 GRAIN KEYS: {', '.join(contract.get('grain_keys', []))}")

                    completeness_line = self._format_completeness(contract.get("completeness"))
                    if completeness_line:
                        formatted.append(f"  🔹 COMPLETENESS: {completeness_line}")
                    grouping_line = self._format_grouping(contract)
                    if grouping_line:
                        formatted.append(f"  🔹 GROUPING: {grouping_line}")

                    # Every row, not the first three. This list is not a display
                    # preview — it is the set of fields the planner is permitted
                    # to name in the next command. Sampling it made "this field
                    # does not exist" and "this field was not on rows 0-2" the
                    # same observable, and a field first carried on row 4 was
                    # then unreachable for the rest of the run. The rows are all
                    # in memory here already, and the per-field type loop stops
                    # at the first non-null value, so this terminates on the
                    # first row carrying each field rather than scanning all of
                    # them.
                    items = value.get("items", [])
                    sample_fields = self._analyze_item_fields(items, row_schema=row_schema)
                    if sample_fields:
                        formatted.append("  🔍 AVAILABLE FIELDS (use these exact names in commands):")
                        for field_name, field_type in sample_fields.items():
                            formatted.append(f"    - {field_name}: {field_type}")
                    elif row_schema:
                        formatted.append("  🔍 AVAILABLE FIELDS (use these exact names in commands):")
                        for field_name in row_schema:
                            formatted.append(f"    - {field_name}: unknown")
                    else:
                        # No rows and no row schema means the fields are not
                        # known. The list that used to sit here named four
                        # fields as available; three of them
                        # (`description`, `source_id`, `clusters`) are not part
                        # of the canonical graph abstraction in
                        # docs/RUNTIME_INVARIANTS.md, so this was a
                        # source-graph-specific schema assumption presented to
                        # the planner as fact. Guessing wrong here is worse than
                        # saying nothing: the planner writes commands against
                        # fields that do not exist and the failure surfaces far
                        # from its cause.
                        formatted.append(
                            "  🔍 AVAILABLE FIELDS: unknown — no rows and no declared row schema"
                        )

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
    
    @staticmethod
    def _format_planner_constraints(records: Any) -> str:
        """Render planner constraints in three DISTINCT states.

        The states are "none were authored", "these are current", and "these are
        standing but were authored earlier and nothing has refreshed them". The
        old bullet formatter collapsed the first into the empty string -- the
        prompt simply had no constraints section, which reads as "no constraints
        section exists in this prompt", not as "no constraints were authored" --
        and had no notion of the third at all.

        The third state is the point. Keeping old constraints standing rather
        than expiring them is the right call, because nothing here can compute
        whether a constraint is still relevant. It is only HONEST if the planner
        is told they are stale, otherwise the engine has silently upgraded an
        old instruction into a current one.
        """
        records = records or []
        if not records:
            return (
                "\n\nPrevious planner constraints: NONE were authored. "
                "This is an absence of constraints, not an omission from this prompt."
            )
        active, unrefreshed = [], []
        for record in records:
            if isinstance(record, dict):
                text = str(record.get("text", "")).strip()
                if not text:
                    continue
                if record.get("status") == "unrefreshed":
                    authored = record.get("authored_iteration")
                    where = f"iteration {authored}" if authored is not None else "an unknown iteration"
                    unrefreshed.append(f"- {text}  [authored {where}; NOT refreshed since]")
                else:
                    active.append(f"- {text}")
            else:
                unrefreshed.append(f"- {record}  [authorship unknown]")

        sections = []
        if active:
            sections.append("\n\nPrevious planner constraints (current):\n" + "\n".join(active))
        if unrefreshed:
            sections.append(
                "\n\nStanding planner constraints, NOT REFRESHED for this attempt:\n"
                + "\n".join(unrefreshed)
                + "\nThese were written for an earlier attempt and no newer repair has "
                "replaced them. They have not been re-judged as relevant; weigh them "
                "accordingly."
            )
        return "".join(sections)

    @staticmethod
    def _format_refinement(art: Any) -> List[str]:
        """Render the retrieval-refinement decision as typed facts only.

        `refinement_note=` is gone. It carried a fresh model-authored paraphrase
        into every planner prompt -- 222 recorded prompt-observation files -- and
        the prose made engine claims the engine had not established, most sharply
        an empty result under a 60-row cap rendered as "no matching edges exist".
        The typed field carried the decision; the prose carried variance.

        The hint never travels alone. `keep` formed on 60 rows, `keep` formed on
        3, and `keep` written because the refinement call failed are three
        different claims, and a bare hint makes them one observable again.
        """
        if not isinstance(art, dict) or art.get("refinement_hint") is None:
            return []
        if art.get("refinement_available") is False:
            trigger = art.get("refinement_trigger") or "unavailable"
            return [f"refinement=NOT JUDGED ({trigger}); retrieval breadth unchanged"]
        facts = [f"refinement_hint={art.get('refinement_hint')}"]
        sample_size = art.get("refinement_sample_size")
        if sample_size is not None:
            facts.append(f"judged_on={sample_size} rows")
        caps = art.get("refinement_caps") or {}
        if caps:
            facts.append(
                "sample_caps=" + ",".join(f"{k}={v}" for k, v in sorted(caps.items()))
            )
        requested = art.get("requested_depth")
        if requested is not None:
            effective = art.get("effective_depth")
            facts.append(
                f"depth={effective} (requested {requested}"
                + ("" if effective == requested else ", NARROWED")
                + ")"
            )
        return facts

    @staticmethod
    def _format_grouping(contract: Any) -> str:
        """Render how a grouping resolved and what it could not group.

        The planner named a column; something else may have been grouped by, or
        rows may have been left out of every group. Both are differences between
        the question asked and the one answered, so both are stated rather than
        left to be inferred from a row count.
        """
        if not isinstance(contract, dict):
            return ""
        parts = []

        diagnostics = contract.get("aggregate_diagnostics")
        if isinstance(diagnostics, dict):
            by_field = diagnostics.get("by_field") or {}
            if by_field.get("resolved") and by_field.get("how") != "exact":
                parts.append(
                    f"grouped by {by_field.get('resolved')!r} for requested "
                    f"{by_field.get('requested')!r} ({by_field.get('how')})"
                )
            presence = diagnostics.get("key_presence") or {}
            ungroupable = presence.get("key_absent", 0) + presence.get("key_present_null", 0)
            if ungroupable:
                parts.append(
                    f"{ungroupable}/{presence.get('rows', 0)} rows carry no usable "
                    f"grouping value and are in no group"
                )

        # A weight column whose derivation is unstated, unknown, or partly a
        # no-provenance default must not read as evidence. This reaches the
        # artifact record already; without rendering it here it would be another
        # disclosure written and read by nothing.
        basis = contract.get("row_weight_basis") or ""
        weight_field = contract.get("row_weight_field") or ""
        if weight_field and basis:
            if is_no_evidence(basis):
                parts.append(
                    f"{weight_field!r} is NOT evidence: at least some rows were "
                    f"weighted by the no-provenance default ({basis})"
                )
            elif WEIGHT_BASIS_UNKNOWN in basis_components(basis):
                parts.append(
                    f"{weight_field!r} has an undeclared derivation ({basis}); "
                    f"do not read it as evidence"
                )
            else:
                parts.append(f"{weight_field!r} derived by {basis}")

        collapse = contract.get("collapse_diagnostics")
        if isinstance(collapse, dict):
            without = collapse.get("groups_without_evidence", 0)
            if without:
                parts.append(
                    f"{without}/{collapse.get('groups', 0)} collapsed groups have no "
                    f"source refs, so no evidence metric is nominated; "
                    f"{collapse.get('contributing_rows_field')!r} counts merged rows, "
                    f"not evidence"
                )
            elif collapse.get("evidence_metric_field"):
                parts.append(
                    f"evidence metric is {collapse.get('evidence_metric_field')!r} "
                    f"(source refs deduplicated across rows)"
                )
        return "; ".join(parts)

    @staticmethod
    def _format_completeness(disclosure: Any) -> str:
        """Render a retrieval's completeness disclosure for the planner.

        Both cases are rendered. Printing only the bounded case would make a
        complete result and a result whose producer never disclosed anything
        look identical in the prompt, and the planner would have no way to tell
        an exhaustive answer from an unaudited one.
        """
        if not isinstance(disclosure, dict) or "complete" not in disclosure:
            return ""

        returned = disclosure.get("returned", 0)
        if disclosure.get("complete"):
            return f"COMPLETE — all {returned} matching rows returned"

        parts = [f"BOUNDED — {returned} rows returned, NOT all matches"]
        bound_kind = disclosure.get("bound_kind") or "unspecified bound"
        bound = disclosure.get("bound")
        parts.append(f"stopped by {bound_kind}" + (f"={bound}" if bound is not None else ""))
        if disclosure.get("residual_known"):
            parts.append(f"{disclosure.get('residual')} matches not returned")
        else:
            parts.append("how many matches remain is unknown")
        # Both units, together. A reader shown only "N nodes truncated" will
        # under-read a heavy-tailed fan-out cut: on the measured graphs that
        # number is under 2% while the edges it stands for are 15-19% of all
        # traversal. The gap has to be visible in one place, not inferable from
        # two.
        truncated_nodes = disclosure.get("nodes_with_truncated_fanout")
        discarded_edges = disclosure.get("edges_discarded_by_fanout_cap")
        if truncated_nodes:
            parts.append(
                f"fan-out cap clipped {truncated_nodes} high-degree nodes, "
                f"discarding {discarded_edges} edges"
            )
        seeds_expanded = disclosure.get("seeds_expanded")
        seeds_total = disclosure.get("seeds_total")
        if isinstance(seeds_expanded, int) and isinstance(seeds_total, int) and seeds_total:
            if seeds_expanded < seeds_total:
                parts.append(f"expanded {seeds_expanded}/{seeds_total} seeds")

        scanned = disclosure.get("pairs_scanned")
        total = disclosure.get("pairs_total")
        if isinstance(scanned, int) and isinstance(total, int) and total > 0:
            parts.append(f"covered {scanned}/{total} candidate pairs")
        return "; ".join(parts)

    def _analyze_item_fields(self, items: List[Dict], row_schema: Optional[List[str]] = None) -> Dict[str, str]:
        """Analyze sample items to determine available fields and their types."""
        if not items and not row_schema:
            return {}

        field_types = {}
        schema = list(row_schema or [])
        if not schema and items:
            # Every row. A schema inferred from a sample is a claim about the
            # payload the payload does not support — see the same reasoning in
            # `gasl.contracts.infer_row_schema`, which stopped sampling for
            # exactly this reason.
            schema = infer_row_schema(items, max_depth=2)

        for field_name in schema:
            if field_name == "_meta":
                continue
            field_type = "unknown"
            for item in items:
                field_value = self._get_path_value(item, field_name)
                candidate = self._value_type(field_value)
                if field_type == "unknown" or candidate not in {"unknown", "null"}:
                    field_type = candidate
                if field_type not in {"unknown", "null"}:
                    break
            field_types[field_name] = field_type

        return field_types

    @staticmethod
    def _get_path_value(item: Any, field_name: str) -> Any:
        current = item
        for part in field_name.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @staticmethod
    def _value_type(value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        if value is None:
            return "null"
        return "unknown"
    
    def _format_history(self, history: list) -> str:
        """Format history for prompt."""
        if not history:
            return "No execution history yet."
        
        formatted = []
        for entry in history:
            status = entry.get("status", "unknown")
            command = entry.get("command", "")
            count = entry.get("result_count", 0)
            formatted.append(f"- {status}: {command} (result count: {count})")

        # Windowed by measured size, not by a count of entries, and the residual
        # is stated. Under the old `[-5:]` a run that had been failing the same
        # way for forty turns rendered identically to a five-turn-old run, so
        # "no signal" and "no problem" were the same observable.
        kept, omitted = self._window_by_size(formatted)
        if omitted:
            kept.insert(0, f"({omitted} earlier entries omitted; {len(formatted)} total)")
        return "\n".join(kept)

    def _format_produced_artifacts(self, artifacts: list) -> str:
        """Format recently produced artifacts for prompt context."""
        if not artifacts:
            return "No produced artifacts yet."
        formatted = []
        for art in artifacts:
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
            if art.get("grain_keys"):
                parts.append(f"grain_keys={art.get('grain_keys')}")
            if art.get("row_schema"):
                parts.append(f"fields={art.get('row_schema', [])}")
            if art.get("safe_for"):
                parts.append(f"safe_for={art.get('safe_for')}")
            parts.extend(self._format_refinement(art))
            completeness_line = self._format_completeness(art.get("completeness"))
            if completeness_line:
                parts.append(completeness_line)
            grouping_line = self._format_grouping(art)
            if grouping_line:
                parts.append(grouping_line)
            formatted.append(", ".join(parts))

        # Same measured window and same disclosure as `_format_history`.
        kept, omitted = self._window_by_size(formatted)
        if omitted:
            kept.insert(0, f"({omitted} earlier artifacts omitted; {len(formatted)} total)")
        return "\n".join(kept)
    
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
