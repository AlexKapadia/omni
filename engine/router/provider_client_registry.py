"""Builds provider clients from the key store — the router never sees keys.

Purpose: the single seam between key custody (``engine.security``) and the
router. It asks the :class:`ProviderKeyStore` which providers are keyed and
hands the executor ready-made CLIENTS; key material flows key-store ->
client constructor and nowhere else.
Pipeline position: called at engine startup (and again after the user
edits keys in Settings) to (re)build the client map the fallback executor
routes over.

Security invariant: only keyed providers get a client at all — an un-keyed
provider is structurally uncallable, not merely "will fail with 401".
"""

from __future__ import annotations

import os

from engine.router.completion_contract import Provider, ProviderCompletionClient
from engine.router.provider_client_anthropic import AnthropicCompletionClient
from engine.router.provider_client_gemini import GeminiCompletionClient
from engine.router.provider_client_groq import GroqCompletionClient
from engine.router.provider_client_openai import OpenAICompletionClient
from engine.security.provider_key_store import ProviderKeyStore
from engine.security.secret_redaction import SecretApiKey

OLLAMA_BASE_URL_ENV = "OMNI_OLLAMA_BASE_URL"
OLLAMA_DEFAULT_MODEL = "llama3.2"


def build_provider_clients(
    key_store: ProviderKeyStore,
) -> dict[Provider, ProviderCompletionClient]:
    """One client per KEYED provider (Anthropic appears only when keyed).

    SDK imports stay lazy inside each client, so building the map is cheap
    and safe even when an SDK is missing — the failure (a clear
    ``ProviderSdkMissingError``) surfaces on first actual use.
    """
    clients: dict[Provider, ProviderCompletionClient] = {}
    groq_key = key_store.get_key(Provider.GROQ.value)
    if groq_key is not None:
        clients[Provider.GROQ] = GroqCompletionClient(groq_key)
    gemini_key = key_store.get_key(Provider.GEMINI.value)
    if gemini_key is not None:
        clients[Provider.GEMINI] = GeminiCompletionClient(gemini_key)
    anthropic_key = key_store.get_key(Provider.ANTHROPIC.value)
    if anthropic_key is not None:
        clients[Provider.ANTHROPIC] = AnthropicCompletionClient(anthropic_key)
    openai_key = key_store.get_key(Provider.OPENAI.value)
    if openai_key is not None:
        clients[Provider.OPENAI] = OpenAICompletionClient(openai_key)
    ollama_url = os.environ.get(OLLAMA_BASE_URL_ENV, "").strip()
    if ollama_url:
        base = ollama_url if ollama_url.endswith("/v1") else f"{ollama_url.rstrip('/')}/v1"
        clients[Provider.OLLAMA] = OpenAICompletionClient(SecretApiKey("ollama"), base_url=base)
    return clients
