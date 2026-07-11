"""live_extraction must honour preferred_provider/model (summary settings).

Bug: prefer_summary_model only ran for enhanced_notes / ask_synthesis, so
Ollama-first Settings were a no-op for the live answers spotter.
"""

from __future__ import annotations

import pytest

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
)
from engine.router.fallback_executor import ProviderRouter
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.router.routing_table import GEMINI_FLASH_MODEL, prefer_summary_model, resolve_route

MESSAGES = (ChatMessage(role="user", content="transcript excerpt (data)"),)


def _ok(provider: Provider, model: str) -> ProviderCompletion:
    return ProviderCompletion(
        text="fine",
        provider=provider,
        model=model,
        prompt_tokens=100,
        completion_tokens=50,
    )


class ScriptedClient(ProviderCompletionClient):
    def __init__(
        self, provider: Provider, script: list[ProviderCompletion]
    ) -> None:
        self.provider = provider
        self._script = list(script)
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.calls.append(request)
        return self._script.pop(0)


class RecordingLedger:
    def __init__(self) -> None:
        self.entries: list[RouterLedgerEntry] = []

    async def record(self, entry: RouterLedgerEntry) -> None:
        self.entries.append(entry)


def test_prefer_summary_model_prepends_ollama_on_live_extraction_when_keyed() -> None:
    """Only Ollama (+ gemini so the base live_extraction chain resolves)
    keyed: preferred_provider=ollama must prepend an ollama slot."""
    keyed = frozenset({"ollama", "gemini"})
    base = resolve_route("live_extraction", keyed)
    preferred = prefer_summary_model(base, None, keyed, preferred_provider="ollama")
    assert preferred.attempts[0].provider == Provider.OLLAMA
    assert preferred.attempts[0].model == "llama3.2"


@pytest.mark.asyncio
async def test_route_live_extraction_applies_prefer_provider_ollama() -> None:
    """ProviderRouter.route must apply prefer for live_extraction, not only
    enhance/ask tasks — otherwise Settings summary_provider is ignored."""
    ledger = RecordingLedger()
    ollama = ScriptedClient(Provider.OLLAMA, [_ok(Provider.OLLAMA, "llama3.2")])
    gemini = ScriptedClient(Provider.GEMINI, [_ok(Provider.GEMINI, GEMINI_FLASH_MODEL)])
    router = ProviderRouter(
        {Provider.OLLAMA: ollama, Provider.GEMINI: gemini}, ledger.record
    )
    result = await router.route(
        "live_extraction",
        "frame",
        MESSAGES,
        preferred_provider="ollama",
    )
    assert result.completion.provider == Provider.OLLAMA
    assert result.completion.model == "llama3.2"
    assert len(ollama.calls) == 1
    assert len(gemini.calls) == 0
