"""Anthropic provider client: the optional premium synthesis/agentic tier.

Purpose: the Claude leg of the tri-provider router. OPTIONAL by session
decision — this client is only ever constructed when an Anthropic key
exists; the routing table promotes it for enhanced_notes, ask_synthesis,
and agentic_tools in that keyed world.
Pipeline position: constructed by ``provider_client_registry``; invoked
only by the fallback executor.

Security / injection posture: identical to the other clients — key material
revealed only into the SDK, all error text redacted, caller ``system_frame``
sent as the top-level ``system`` parameter while transcript/document content
rides in ``messages`` as DATA (prompt-injection defence at the boundary).

The ``anthropic`` package is imported lazily; a missing package fails
closed with a clear, named error.
"""

import importlib
import json
from typing import Any

from engine.router.completion_contract import (
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
    ToolCall,
)
from engine.router.provider_error_translation import translate_sdk_exception
from engine.router.router_errors import ProviderSdkMissingError
from engine.security.secret_redaction import SecretApiKey


def _load_anthropic_sdk() -> Any:
    """Import the official SDK lazily; fail closed naming the package."""
    try:
        return importlib.import_module("anthropic")
    except ImportError as exc:
        raise ProviderSdkMissingError("anthropic", "anthropic") from exc


class AnthropicCompletionClient(ProviderCompletionClient):
    """Messages-API client for Claude models."""

    provider = Provider.ANTHROPIC

    def __init__(self, api_key: SecretApiKey) -> None:
        self._api_key = api_key
        self._sdk_client: Any = None  # built on first use (lazy SDK import)

    def _client(self) -> Any:
        if self._sdk_client is None:
            sdk = _load_anthropic_sdk()
            # max_retries=0: retry policy belongs to the fallback executor,
            # uniformly — the SDK must not stack its own retries on top.
            self._sdk_client = sdk.AsyncAnthropic(
                api_key=self._api_key.reveal(), max_retries=0
            )
        return self._sdk_client

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        """One completion call; SDK errors surface as typed, redacted errors."""
        payload: dict[str, Any] = {
            "model": request.model,
            # Instruction channel: caller's frame only, as the system param.
            "system": request.system_frame,
            # Data channel: untrusted content stays in its own turns.
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            # Latency budget from the routing table, enforced SDK-side.
            "timeout": request.timeout_seconds,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters_json_schema,
                }
                for t in request.tools
            ]
        # Structured output: no native json_schema mode on the Messages API —
        # the caller's system frame carries the schema instructions
        # (documented contract; M2 pipelines own the framing).
        try:
            response = await self._client().messages.create(**payload)
        except Exception as exc:
            # `from None`: the raw SDK exception may carry unredacted request
            # detail; suppressing the chain keeps it out of any exc_info log
            # (redaction invariant). The redacted message preserves the story.
            raise translate_sdk_exception(
                exc, provider=self.provider.value, model=request.model, api_key=self._api_key
            ) from None
        return _completion_from_response(response, request.model)


def _completion_from_response(response: Any, model: str) -> ProviderCompletion:
    """Normalise content blocks; provider-reported usage passes through
    EXACTLY (the ledger's cost arithmetic depends on it)."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(name=block.name, arguments_json=json.dumps(block.input)))
    return ProviderCompletion(
        text="".join(text_parts),
        provider=Provider.ANTHROPIC,
        model=model,
        prompt_tokens=int(response.usage.input_tokens),
        completion_tokens=int(response.usage.output_tokens),
        tool_calls=tuple(tool_calls),
    )
