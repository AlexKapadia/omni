"""Prove the Gemini client CANCELS a slow in-flight call at the budget.

Why this exists: the fallback-cascade suite tests timeout *errors* with fakes
that raise immediately — it never proves that a provider coroutine that simply
hangs is cancelled by ``asyncio.wait_for`` at ``timeout_seconds``. A live smoke
observed a 12.1s wall time on a 3.5s-budget task (explained by multi-attempt
accumulation across the fallback chain), so this pins the single-attempt
guarantee: one slow attempt ends at the budget, not at the provider's leisure.
"""

import asyncio
import time
from typing import Any

import pytest

from engine.router.completion_contract import ChatMessage, CompletionRequest, TaskType
from engine.router.provider_client_gemini import GeminiCompletionClient
from engine.router.router_errors import ProviderCallError, ProviderErrorClass
from engine.security.secret_redaction import SecretApiKey


class _HangingModels:
    """Stub for genai aio.models that hangs far past any sane budget."""

    async def generate_content(self, **_kwargs: Any) -> Any:
        await asyncio.sleep(30)  # never legitimately reached in this test


class _HangingAio:
    models = _HangingModels()


class _HangingSdkClient:
    aio = _HangingAio()


@pytest.mark.asyncio
async def test_slow_gemini_call_is_cancelled_at_timeout_budget() -> None:
    client = GeminiCompletionClient(api_key=SecretApiKey("test-key-not-real"))
    # Inject the hanging stub past the lazy SDK loader (test seam: the
    # cancellation semantics live in our wrapper, not the SDK).
    client._sdk_client = _HangingSdkClient()

    request = CompletionRequest(
        task_type=TaskType.ASK_SYNTHESIS,
        model="gemini-2.5-flash",
        system_frame="test",
        messages=(ChatMessage(role="user", content="test"),),
        max_tokens=16,
        timeout_seconds=0.5,
    )
    started = time.monotonic()
    with pytest.raises(ProviderCallError) as excinfo:
        await client.complete(request)
    elapsed = time.monotonic() - started
    assert excinfo.value.error_class is ProviderErrorClass.TIMEOUT
    # Budget 0.5s: must fire promptly (scheduler slack allowed), never run on.
    assert elapsed < 2.0, f"cancellation took {elapsed:.2f}s — wait_for not effective"
