"""Protocol v1 payloads for the M7 provider API-key command surface.

Purpose: pinned names and strict payload models for ``keys.save`` (masked
input -> DPAPI store) and ``keys.validate`` (one real 1-token call).
Pipeline position: consumed by
``engine.wiring.provider_keys_command_dispatcher`` and the UI.

Security invariants:
- The key value rides as a pydantic ``SecretStr`` so reprs/validation
  errors can never echo it (keys are never logged, never reflected back —
  claude.md §5.6 DPAPI binding).
- ``extra="forbid"`` — payloads are untrusted input, deny by default.
- The provider enum here is the closed set the key store accepts; anything
  else is an invalid payload before any code touches the value.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

COMMAND_KEYS_SAVE = "keys.save"
COMMAND_KEYS_VALIDATE = "keys.validate"

# The closed provider set for key custody. Groq + Gemini are required by the
# product; Anthropic and Cartesia are optional slots (session decision).
KeyProviderName = Literal["groq", "gemini", "anthropic", "cartesia"]

# Sanity bounds on pasted keys: long enough to be real, short enough to not
# be an abuse vector (a 4 KiB "key" is not a key).
_MIN_KEY_CHARS = 8
_MAX_KEY_CHARS = 512


class KeysSaveCommandPayload(BaseModel):
    """``keys.save`` — one provider, one key value (write-only)."""

    model_config = ConfigDict(extra="forbid")

    provider: KeyProviderName
    key: SecretStr = Field(min_length=_MIN_KEY_CHARS, max_length=_MAX_KEY_CHARS)


class KeysValidateCommandPayload(BaseModel):
    """``keys.validate`` — validate the STORED key for one provider with a
    single real, minimal call. The key value itself never rides this
    command (save first, then validate)."""

    model_config = ConfigDict(extra="forbid")

    provider: KeyProviderName
