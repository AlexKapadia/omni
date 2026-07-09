"""Live provider-key validation: one real, minimal call per provider.

Purpose: the honest "is this key actually valid?" check behind
``keys.validate`` — a single 1-token completion for Groq / Gemini /
Anthropic, and a single voices-list GET for Cartesia. Success and failure
are reported exactly as observed (with the real latency), never guessed.
Pipeline position: called by
``engine.wiring.provider_keys_command_dispatcher``; sits above
``engine.router`` provider clients and ``engine.security``.

Security invariants:
- KILL SWITCH IS HONOURED: validation is an external call, so an engaged
  switch refuses it outright (fail closed on egress).
- Keys resolve through :class:`ProviderKeyStore` only (DPAPI store first,
  dev env fallback) — the key value never rides the command.
- Error text passes through the router's redaction-aware translation for
  LLM providers; the Cartesia path reports status codes only. No key
  material can appear in any message.
"""

import time
from dataclasses import dataclass

from engine.router.completion_contract import (
    ChatMessage,
    CompletionRequest,
    Provider,
    TaskType,
)
from engine.router.provider_client_registry import build_provider_clients
from engine.router.routing_table import (
    ANTHROPIC_MODEL,
    AZURE_OPENAI_DEFAULT_MODEL,
    GEMINI_FLASH_MODEL,
    GROQ_FAST_MODEL,
    OPENAI_MINI_MODEL,
    OPENROUTER_DEFAULT_MODEL,
)
from engine.security.kill_switch import kill_switch_engaged
from engine.security.provider_key_store import ProviderKeyStore
from engine.voice.cartesia_message_framing import CARTESIA_API_VERSION

# The cheapest sensible model per LLM provider for a 1-token probe.
_VALIDATION_MODEL_BY_PROVIDER = {
    Provider.GROQ: GROQ_FAST_MODEL,
    Provider.GEMINI: GEMINI_FLASH_MODEL,
    Provider.ANTHROPIC: ANTHROPIC_MODEL,
    Provider.OPENAI: OPENAI_MINI_MODEL,
    Provider.OPENROUTER: OPENROUTER_DEFAULT_MODEL,
    Provider.AZURE_OPENAI: AZURE_OPENAI_DEFAULT_MODEL,
}

_VALIDATION_TIMEOUT_SECONDS = 15.0

# Cartesia REST probe: the lightest authenticated endpoint (list voices).
_CARTESIA_VOICES_URL = "https://api.cartesia.ai/voices?limit=1"


@dataclass(frozen=True)
class KeyValidationResult:
    """The honest outcome of one validation call."""

    provider: str
    valid: bool
    message: str
    latency_ms: int | None  # measured wall clock on success; None otherwise


async def validate_provider_key(
    provider: str, key_store: ProviderKeyStore | None = None
) -> KeyValidationResult:
    """Validate the STORED key for ``provider`` with one real minimal call."""
    if kill_switch_engaged():
        # Fail closed on egress: no external call while the switch is on.
        return KeyValidationResult(
            provider, False, "kill switch engaged — external calls are refused", None
        )
    store = key_store if key_store is not None else ProviderKeyStore()
    if store.get_key(provider) is None:
        return KeyValidationResult(provider, False, "no key saved for this provider", None)
    if provider == "cartesia":
        return await _validate_cartesia_key(store)
    return await _validate_llm_key(provider, store)


async def _validate_llm_key(provider: str, store: ProviderKeyStore) -> KeyValidationResult:
    """One 1-token completion against the provider's cheapest routed model."""
    provider_enum = Provider(provider)  # payload enum guarantees membership
    client = build_provider_clients(store).get(provider_enum)
    if client is None:
        return KeyValidationResult(provider, False, "no key saved for this provider", None)
    request = CompletionRequest(
        task_type=TaskType.INTENT_PARSING,  # cheapest routed lane; content is trivial
        model=_VALIDATION_MODEL_BY_PROVIDER[provider_enum],
        system_frame="Reply with the single word: ok",
        messages=(ChatMessage(role="user", content="ok"),),
        timeout_seconds=_VALIDATION_TIMEOUT_SECONDS,
        max_tokens=1,
    )
    started = time.monotonic()
    try:
        await client.complete(request)
    except Exception as exc:
        # The provider client already raised a REDACTED ProviderCallError
        # (key material scrubbed at the client boundary — provider_error_
        # translation); surfacing its message can never leak a key.
        return KeyValidationResult(provider, False, str(exc), None)
    latency_ms = int((time.monotonic() - started) * 1000)
    return KeyValidationResult(
        provider, True, f"key is valid — the model answered in {latency_ms} ms", latency_ms
    )


async def _validate_cartesia_key(store: ProviderKeyStore) -> KeyValidationResult:
    """One authenticated voices-list GET (no audio, no cost)."""
    import httpx  # Lazy: only the validation path needs an HTTP client here.

    key = store.get_key("cartesia")
    if key is None:  # pragma: no cover — guarded by the caller
        return KeyValidationResult("cartesia", False, "no key saved for this provider", None)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_VALIDATION_TIMEOUT_SECONDS) as client:
            response = await client.get(
                _CARTESIA_VOICES_URL,
                # Key revealed ONLY into the auth header, never logged.
                headers={
                    "X-API-Key": key.reveal(),
                    "Cartesia-Version": CARTESIA_API_VERSION,
                },
            )
    except httpx.HTTPError as exc:
        # Status-code-free transport errors: report the class, not the body.
        return KeyValidationResult(
            "cartesia", False, f"could not reach Cartesia ({type(exc).__name__})", None
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code == 200:
        return KeyValidationResult(
            "cartesia", True, f"key is valid — Cartesia answered in {latency_ms} ms", latency_ms
        )
    if response.status_code in (401, 403):
        return KeyValidationResult(
            "cartesia", False, "Cartesia rejected the key (unauthorized)", None
        )
    return KeyValidationResult(
        "cartesia", False, f"Cartesia answered with status {response.status_code}", None
    )
