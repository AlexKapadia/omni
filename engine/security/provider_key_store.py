"""DPAPI-encrypted provider API-key custody with a dev-mode env fallback.

Purpose: the ONLY place provider API keys are read or written. Keys entered
in the onboarding wizard are DPAPI-encrypted (per Windows user) into
``%LOCALAPPDATA%/Omni/keys.bin``; in development the well-known environment
variables (GROQ_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY — loaded from
``.env`` by the DEV RUNNER, never by engine code) act as a fallback.
Pipeline position: consumed by ``engine.router.provider_client_registry``,
which asks for clients' key material here and hands back CLIENTS — the
router itself never sees a key.

Security invariants (claude.md §5.6 project bindings):
- Plaintext keys never touch disk: the on-disk blob is DPAPI ciphertext.
- Engine code NEVER reads ``.env`` directly — only the process environment.
- Keys leave this module only wrapped in :class:`SecretApiKey` (redacting
  repr/str); raw values are revealed solely inside SDK client constructors.
- No key material in logs or errors, ever.
"""

import json
import os
from pathlib import Path

from engine.security.dpapi_windows_crypto import dpapi_protect, dpapi_unprotect
from engine.security.secret_redaction import SecretApiKey

# Canonical provider names, shared with engine.router's Provider enum values.
# WHY strings here: security must not import router (dependency direction —
# router depends on security, never the reverse).
# "cartesia" (M7): the optional voice-provider key rides the same DPAPI
# custody; the router never builds a client for it (voice resolves it).
KNOWN_PROVIDERS = (
    "groq",
    "gemini",
    "anthropic",
    "openai",
    "openrouter",
    "azure_openai",
    "ollama",
    "cartesia",
)

# Dev-mode fallback env vars, per provider (populated by the dev runner).
_ENV_VAR_BY_PROVIDER = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "cartesia": "CARTESIA_API_KEY",
}


def default_key_store_path() -> Path:
    """``%LOCALAPPDATA%/Omni/keys.bin``, mirroring the database's location.

    Falls back to the home directory on non-Windows (CI runners) so the
    path is always user-private, never a world-readable shared directory.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "Omni" / "keys.bin"


class ProviderKeyStore:
    """Reads/writes DPAPI-encrypted provider keys, with env dev fallback.

    Precedence per provider: the encrypted store wins over the environment —
    a key the user deliberately saved in-app beats a stale dev variable.

    Failure modes: DPAPI errors propagate (fail closed — a corrupt or
    foreign-user blob must never be silently treated as "no keys").
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = store_path if store_path is not None else default_key_store_path()

    def get_key(self, provider: str) -> SecretApiKey | None:
        """The key for ``provider``, or ``None`` when genuinely un-keyed."""
        stored = self._read_encrypted_store().get(provider)
        if stored:
            return SecretApiKey(stored)
        env_var = _ENV_VAR_BY_PROVIDER.get(provider)
        # Dev-mode fallback: process environment only — never .env directly.
        env_value = os.environ.get(env_var, "").strip() if env_var else ""
        if env_value:
            return SecretApiKey(env_value)
        return None

    def set_key(self, provider: str, key: SecretApiKey) -> None:
        """Persist one provider key, DPAPI-encrypted, creating the store."""
        if provider not in KNOWN_PROVIDERS:
            # Deny by default: refuse to store keys for unknown providers.
            raise ValueError(f"unknown provider {provider!r}")
        keys = self._read_encrypted_store()
        keys[provider] = key.reveal()  # plaintext exists only in memory here
        self._write_encrypted_store(keys)

    def delete_key(self, provider: str) -> None:
        """Remove a stored key (env fallback may still apply afterwards)."""
        keys = self._read_encrypted_store()
        if provider in keys:
            del keys[provider]
            self._write_encrypted_store(keys)

    def keyed_providers(self) -> frozenset[str]:
        """Providers currently resolvable to a key (store OR env fallback).

        The routing table uses this to decide the anthropic-if-keyed slots.
        """
        providers = frozenset(p for p in KNOWN_PROVIDERS if self.get_key(p) is not None)
        if os.environ.get("OMNI_OLLAMA_BASE_URL", "").strip():
            providers = providers | frozenset({"ollama"})
        if os.environ.get("OMNI_LMSTUDIO_BASE_URL", "").strip():
            providers = providers | frozenset({"lm_studio"})
        endpoint = os.environ.get("OMNI_AZURE_OPENAI_ENDPOINT", "").strip()
        if endpoint and self.get_key("azure_openai") is not None:
            providers = providers | frozenset({"azure_openai"})
        return providers

    def _read_encrypted_store(self) -> dict[str, str]:
        """Decrypt and parse keys.bin; missing file means an empty store."""
        if not self._store_path.exists():
            return {}
        ciphertext = self._store_path.read_bytes()
        # DPAPI decrypt: per-user; raises (fail closed) on tamper/other-user.
        plaintext = dpapi_unprotect(ciphertext)
        parsed = json.loads(plaintext.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("key store blob is not a JSON object")
        return {str(k): str(v) for k, v in parsed.items()}

    def _write_encrypted_store(self, keys: dict[str, str]) -> None:
        """Serialise, DPAPI-encrypt, and write the whole store atomically."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        ciphertext = dpapi_protect(json.dumps(keys).encode("utf-8"))
        # Write-then-replace: a crash mid-write can never leave a truncated
        # blob where the real store was (the old store survives intact).
        temp_path = self._store_path.with_suffix(".bin.tmp")
        temp_path.write_bytes(ciphertext)
        temp_path.replace(self._store_path)
