"""Gemini provider client: long-context + fallback tier via google-genai.

Purpose: the Gemini leg of the tri-provider router — primary for
long_context_bulk, the standing fallback for the live paths, and the
function-calling engine for agentic work when Anthropic is not keyed.
Pipeline position: constructed by ``provider_client_registry``; invoked
only by the fallback executor.

Security / injection posture: identical to the other clients — key material
revealed only into the SDK, all error text redacted, caller ``system_frame``
sent as ``system_instruction`` while transcript/document content rides in
``contents`` as DATA (prompt-injection defence at the boundary).

The ``google-genai`` package is imported lazily; a missing package fails
closed with a clear, named error.
"""

import asyncio
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


def _load_genai_sdk() -> Any:
    """Import the official SDK lazily; fail closed naming the package."""
    try:
        return importlib.import_module("google.genai")
    except ImportError as exc:
        raise ProviderSdkMissingError("gemini", "google-genai") from exc


class GeminiCompletionClient(ProviderCompletionClient):
    """generate_content client for the Gemini API (google-genai SDK)."""

    provider = Provider.GEMINI

    def __init__(self, api_key: SecretApiKey) -> None:
        self._api_key = api_key
        self._sdk_client: Any = None  # built on first use (lazy SDK import)

    def _client(self) -> Any:
        if self._sdk_client is None:
            sdk = _load_genai_sdk()
            self._sdk_client = sdk.Client(api_key=self._api_key.reveal())
        return self._sdk_client

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        """One completion call; SDK errors surface as typed, redacted errors."""
        config: dict[str, Any] = {
            # Instruction channel: caller's frame only (never mixed with data).
            "system_instruction": request.system_frame,
            "max_output_tokens": request.max_tokens,
        }
        if request.tools:
            config["tools"] = [
                {
                    "function_declarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters_json_schema,
                        }
                        for t in request.tools
                    ]
                }
            ]
        if request.json_schema is not None:
            # Gemini native structured output: schema-constrained decoding.
            config["response_mime_type"] = "application/json"
            config["response_schema"] = request.json_schema
        # Data channel: transcript/document content as role-tagged parts.
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
        ]
        try:
            # google-genai has no per-request timeout parameter on the async
            # path, so the routing table's latency budget is enforced here.
            response = await asyncio.wait_for(
                self._client().aio.models.generate_content(
                    model=request.model, contents=contents, config=config
                ),
                timeout=request.timeout_seconds,
            )
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
    tool_calls = tuple(
        ToolCall(name=call.name, arguments_json=json.dumps(dict(call.args or {})))
        for call in (getattr(response, "function_calls", None) or ())
    )
    usage = response.usage_metadata
    return ProviderCompletion(
        text=response.text or "",
        provider=Provider.GEMINI,
        model=model,
        prompt_tokens=int(usage.prompt_token_count or 0),
        completion_tokens=int(usage.candidates_token_count or 0),
        tool_calls=tool_calls,
    )
