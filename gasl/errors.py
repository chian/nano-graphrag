"""
Custom exceptions for GASL system.
"""
from __future__ import annotations

from collections.abc import Mapping


class ProviderRunInterrupted(BaseException):
    """Interrupt required provider work without becoming an observation.

    Derive from BaseException so task-level Exception handlers cannot turn a
    provider failure into a failed observation, fallback, or another strategy.
    This is distinct from cancellation and from ordinary retryable LLM errors.
    """

    reason = "provider_run_interrupted"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str | None = None,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code


class ProviderCreditExhausted(ProviderRunInterrupted):
    """A provider explicitly refused work because credits were exhausted."""

    reason = "provider_credit_exhausted"


class ModelCallFailed(ProviderRunInterrupted):
    """Required model work exhausted its allowed retries without a result."""

    reason = "model_call_failed"


def raise_for_provider_credit_exhaustion(
    error: BaseException | None = None,
    *,
    response=None,
    content: str | None = None,
    provider: str,
    model: str | None = None,
) -> None:
    """Promote explicit credit/quota refusals before provider retry/fallback.

    Inspect structured error bodies and their messages, including wrapped SDK
    errors. HTTP 402, billing_error, and HTTP 429 alone do not prove exhausted
    credits; a credit-specific code or message must be present.
    """

    if isinstance(error, ProviderCreditExhausted):
        raise error
    codes = {
        "credit_balance_exhausted",
        "credits_exhausted",
        "credit_exhausted",
        "insufficient_credits",
        "insufficient_credit",
        "insufficient_balance",
        "insufficient_quota",
        "credit_limit_exceeded",
        "billing_hard_limit_reached",
    }
    phrases = (
        "no available typesafe api credits",
        "insufficient credit",
        "not enough credit",
        "out of credit",
        "credit balance is too low",
        "credit balance too low",
        "credit balance exhausted",
        "credits have been exhausted",
        "credits are exhausted",
        "exhausted your credits",
        "exceeded your current quota",
    )
    messages: list[str] = []
    successful_content: list[str] = [content] if isinstance(content, str) else []
    status_code = None
    pending = [error] if error is not None else []
    responses = [response] if response is not None else []
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        messages.append(str(current))
        status_code = status_code or getattr(current, "status_code", None)
        responses.append(getattr(current, "response", None))
        for name in ("body", "code", "type"):
            value = getattr(current, name, None)
            if value is not None:
                responses.append(value)
        for name in ("__cause__", "__context__"):
            linked = getattr(current, name, None)
            if linked is not None:
                pending.append(linked)

    def collect(value) -> None:
        if isinstance(value, str):
            messages.append(value)
        elif isinstance(value, Mapping):
            for key in ("error", "errors", "detail", "message", "code", "type", "error_type"):
                if key in value:
                    collect(value[key])
        elif isinstance(value, (tuple, list)):
            for item in value:
                collect(item)

    for item in responses:
        if item is None:
            continue
        if isinstance(item, (str, Mapping, tuple, list)):
            collect(item)
            continue
        status_code = status_code or getattr(item, "status_code", None)
        # A successful Argo response can carry a refusal in its completion.
        # Keep that separate: ordinary model text about billing is not proof.
        if getattr(item, "status_code", 0) < 400:
            try:
                body = item.json()
            except (TypeError, ValueError):
                successful_content.append(str(getattr(item, "text", "")))
            else:
                if isinstance(body, str):
                    successful_content.append(body)
                elif isinstance(body, Mapping):
                    for choice in body.get("choices") or ():
                        if isinstance(choice, Mapping):
                            message = choice.get("message")
                            if isinstance(message, Mapping) and isinstance(
                                message.get("content"), str
                            ):
                                successful_content.append(message["content"])
            continue
        try:
            collect(item.json())
        except (TypeError, ValueError):
            pass
        collect(getattr(item, "text", ""))

    quota_notice = "your argo usage limit has been exceeded."
    for value in successful_content:
        # Argo's observed notice decorates its leading heading with warning /
        # access-denied emoji and Markdown. Strip only that known formatting.
        normalized_content = value.strip().lstrip("#* \t\r\n⚠️🚫").casefold()
        if normalized_content.startswith(
            ("important usage notice from argo", "access revoked", quota_notice)
        ) and quota_notice in normalized_content:
            messages.append(value)

    normalized = [message.casefold() for message in messages]
    if not any(
        any(code in message for code in codes)
        or any(phrase in message for phrase in phrases)
        or quota_notice in message
        for message in normalized
    ):
        return
    detail = next((message for message in messages if message.strip()), "")
    raise ProviderCreditExhausted(
        f"Run interrupted: {provider} credits exhausted"
        + (f" (HTTP {status_code})" if status_code is not None else "")
        + (f": {detail[:4000]}" if detail else ""),
        provider=provider,
        model=model,
        status_code=status_code,
    ) from error


class GASLError(Exception):
    """Base exception for all GASL-related errors."""
    pass


class ParseError(GASLError):
    """Raised when GASL command parsing fails."""
    
    def __init__(self, message: str, command: str = None, line_number: int = None):
        super().__init__(message)
        self.command = command
        self.line_number = line_number


class ExecutionError(GASLError):
    """Raised when command execution fails."""
    
    def __init__(self, message: str, command: str = None, step_id: str = None):
        super().__init__(message)
        self.command = command
        self.step_id = step_id


class AdapterError(GASLError):
    """Raised when graph adapter operations fail."""
    
    def __init__(self, message: str, adapter_type: str = None, operation: str = None):
        super().__init__(message)
        self.adapter_type = adapter_type
        self.operation = operation


class AdapterCapabilityError(AdapterError):
    """Raised when a filter is well-formed but this backend cannot translate it.

    Distinct from `AdapterError` on purpose. A malformed filter is a caller
    error and rewriting the command can fix it; an untranslated filter is a
    property of the backend and no rewrite of the command will ever satisfy it.
    Collapsing the two sends the repair loop to rewrite a perfectly good command
    against an unrepairable condition, burning a call per attempt.
    """

    def __init__(
        self,
        message: str,
        adapter_type: str = None,
        operation: str = None,
        *,
        unsupported_keys: list[str] | None = None,
        surface: str = None,
    ):
        super().__init__(message, adapter_type, operation)
        self.unsupported_keys = list(unsupported_keys or [])
        self.surface = surface
        # Retrying the same command against the same adapter cannot succeed.
        self.retryable = False


class StateError(GASLError):
    """Raised when state operations fail."""
    
    def __init__(self, message: str, state_key: str = None, operation: str = None):
        super().__init__(message)
        self.state_key = state_key
        self.operation = operation


class LLMError(GASLError):
    """Raised when LLM interactions fail."""
    
    def __init__(
        self,
        message: str,
        provider: str = None,
        model: str = None,
        *,
        category: str = "unknown",
        status_code: int | None = None,
        original_type: str | None = None,
        fatal: bool = False,
        retry_after: str | float | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.category = category
        self.status_code = status_code
        self.original_type = original_type
        self.fatal = fatal
        self.retry_after = retry_after
