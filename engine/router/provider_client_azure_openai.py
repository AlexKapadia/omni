"""Azure OpenAI provider client."""

from __future__ import annotations

import importlib
import os
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

AZURE_OPENAI_ENDPOINT_ENV = "OMNI_AZURE_OPENAI_ENDPOINT"
AZURE_OPENAI_DEPLOYMENT_ENV = "OMNI_AZURE_OPENAI_DEPLOYMENT"
AZURE_OPENAI_API_VERSION_ENV = "OMNI_AZURE_OPENAI_API_VERSION"
AZURE_OPENAI_DEFAULT_DEPLOYMENT = "gpt-4o-mini"
AZURE_OPENAI_DEFAULT_API_VERSION = "2024-02-15-preview"


def _load_openai_sdk() -> Any:
    try:
        return importlib.import_module("openai")
    except ImportError as exc:
        raise ProviderSdkMissingError("azure_openai", "openai") from exc


class AzureOpenAICompletionClient(ProviderCompletionClient):
    provider = Provider.AZURE_OPENAI

    def __init__(self, api_key: SecretApiKey) -> None:
        self._api_key = api_key
        self._sdk_client: Any = None
        self._deployment = (
            os.environ.get(AZURE_OPENAI_DEPLOYMENT_ENV, "").strip()
            or AZURE_OPENAI_DEFAULT_DEPLOYMENT
        )

    def _client(self) -> Any:
        if self._sdk_client is None:
            endpoint = os.environ.get(AZURE_OPENAI_ENDPOINT_ENV, "").strip()
            if not endpoint:
                raise RuntimeError("OMNI_AZURE_OPENAI_ENDPOINT is not configured")
            api_version = (
                os.environ.get(AZURE_OPENAI_API_VERSION_ENV, "").strip()
                or AZURE_OPENAI_DEFAULT_API_VERSION
            )
            sdk = _load_openai_sdk()
            self._sdk_client = sdk.AsyncAzureOpenAI(
                api_key=self._api_key.reveal(),
                azure_endpoint=endpoint,
                api_version=api_version,
                max_retries=0,
            )
        return self._sdk_client

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        model = request.model if request.model else self._deployment
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_frame},
                *({"role": m.role, "content": m.content} for m in request.messages),
            ],
            "max_tokens": request.max_tokens,
            "timeout": request.timeout_seconds,
        }
        if request.json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = await self._client().chat.completions.create(**payload)
        except Exception as exc:
            raise translate_sdk_exception(
                exc, provider=self.provider.value, model=model, api_key=self._api_key
            ) from None
        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls = tuple(
            ToolCall(name=tc.function.name, arguments_json=tc.function.arguments)
            for tc in (choice.message.tool_calls or [])
            if tc.function is not None
        )
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return ProviderCompletion(
            text=text,
            provider=self.provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_calls=tool_calls,
        )
