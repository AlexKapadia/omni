"""Groq provider client: instant-tier completions via the official SDK.

Purpose: the Groq leg of the tri-provider router — serves the live paths
(live_extraction, intent_parsing) where Groq's inference speed is the
point. Implements the narrow ``ProviderCompletionClient`` contract.
Pipeline position: constructed by ``provider_client_registry`` (which owns
key retrieval); invoked only by the fallback executor.

Security / injection posture:
- The API key arrives as a ``SecretApiKey`` and is revealed ONLY into the
  SDK constructor; every error message is redacted before propagating.
- ``system_frame`` (caller-authored instructions) is sent as the system
  message; transcript/document content rides in user/assistant messages as
  DATA — the two channels are never concatenated (prompt-injection defence
  at the boundary; full framework lands with M2 pipelines).

The ``groq`` package is imported lazily so the engine (and the test suite,
which mocks at this client boundary) loads without it; a missing package
fails closed with a clear, named error.
"""

import importlib
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


def _load_groq_sdk() -> Any:
    """Import the official SDK lazily; fail closed naming the package."""
    try:
        return importlib.import_module("groq")
    except ImportError as exc:
        raise ProviderSdkMissingError("groq", "groq") from exc


class GroqCompletionClient(ProviderCompletionClient):
    """Chat-completions client for Groq's OpenAI-compatible API."""

    provider = Provider.GROQ

    def __init__(self, api_key: SecretApiKey) -> None:
        self._api_key = api_key
        self._sdk_client: Any = None  # built on first use (lazy SDK import)

    def _client(self) -> Any:
        if self._sdk_client is None:
            sdk = _load_groq_sdk()
            # max_retries=0: retry policy belongs to the fallback executor,
            # uniformly — the SDK must not stack its own retries on top.
            self._sdk_client = sdk.AsyncGroq(api_key=self._api_key.reveal(), max_retries=0)
        return self._sdk_client

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        """One completion call; SDK errors surface as typed, redacted errors."""
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                # Instruction channel: caller's frame only.
                {"role": "system", "content": request.system_frame},
                # Data channel: untrusted content stays in its own turns.
                *({"role": m.role, "content": m.content} for m in request.messages),
            ],
            "max_tokens": request.max_tokens,
            # Latency budget from the routing table, enforced SDK-side.
            "timeout": request.timeout_seconds,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters_json_schema,
                    },
                }
                for t in request.tools
            ]
        if request.json_schema is not None:
            # Groq structured output: JSON mode; the caller's system frame
            # carries the schema instructions (documented contract).
            payload["response_format"] = {"type": "json_object"}
        try:
            response = await self._client().chat.completions.create(**payload)
        except Exception as exc:
            # `from None`: the raw SDK exception may carry unredacted request
            # detail; suppressing the chain keeps it out of any exc_info log
            # (redaction invariant). The redacted message preserves the story.
            raise translate_sdk_exception(
                exc, provider=self.provider.value, model=request.model, api_key=self._api_key
            ) from None
        return _completion_from_response(response, request.model)


def _completion_from_response(response: Any, model: str) -> ProviderCompletion:
    """Normalise the SDK response; provider-reported usage passes through
    EXACTLY (the ledger's cost arithmetic depends on it)."""
    message = response.choices[0].message
    tool_calls = tuple(
        ToolCall(name=call.function.name, arguments_json=call.function.arguments)
        for call in (message.tool_calls or ())
    )
    return ProviderCompletion(
        text=message.content or "",
        provider=Provider.GROQ,
        model=model,
        prompt_tokens=int(response.usage.prompt_tokens),
        completion_tokens=int(response.usage.completion_tokens),
        tool_calls=tool_calls,
    )
