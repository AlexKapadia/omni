"""OpenAI-compatible provider client (OpenAI API and compatible endpoints)."""

from __future__ import annotations

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

OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


def _load_openai_sdk() -> Any:
    try:
        return importlib.import_module("openai")
    except ImportError as exc:
        raise ProviderSdkMissingError("openai", "openai") from exc


class OpenAICompletionClient(ProviderCompletionClient):
    provider = Provider.OPENAI

    def __init__(self, api_key: SecretApiKey, *, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._sdk_client: Any = None

    def _client(self) -> Any:
        if self._sdk_client is None:
            sdk = _load_openai_sdk()
            kwargs: dict[str, Any] = {"api_key": self._api_key.reveal(), "max_retries": 0}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._sdk_client = sdk.AsyncOpenAI(**kwargs)
        return self._sdk_client

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        payload: dict[str, Any] = {
            "model": request.model,
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
                exc, provider=self.provider.value, model=request.model, api_key=self._api_key
            ) from None
        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls = tuple(
            ToolCall(name=tc.function.name, arguments_json=tc.function.arguments)
            for tc in (choice.message.tool_calls or [])
            if tc.function is not None
        )
        return ProviderCompletion(text=text, tool_calls=tool_calls)
