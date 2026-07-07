"""Cartesia credential resolution: DPAPI key store → env → SecretApiKey.

Purpose: the ONLY place Cartesia credentials are read. The API key resolves
through ``engine.security.provider_key_store`` (M7: onboarding-entered keys
are DPAPI-encrypted; the well-known env vars remain the dev fallback —
engine code NEVER reads .env directly). CARTESIA_VOICE_ID stays env-only
(an identifier, not a secret).
Pipeline position: consumed by ``tts_playback_streamer`` when it builds the
default Cartesia client.

Security invariants (claude.md §5.6):
- The key leaves this module only wrapped in SecretApiKey (redacting repr).
- Error messages name the VARIABLE, never any value.
- No logging in this module at all — nothing here may ever be printed.
"""

import os
from dataclasses import dataclass

from engine.security import SecretApiKey
from engine.security.provider_key_store import ProviderKeyStore
from engine.voice.voice_errors import VoiceNotConfiguredError

CARTESIA_API_KEY_ENV_VAR = "CARTESIA_API_KEY"
CARTESIA_VOICE_ID_ENV_VAR = "CARTESIA_VOICE_ID"


@dataclass(frozen=True)
class CartesiaCredentials:
    """The pair every Cartesia call needs. voice_id is an identifier, not a
    secret, but is treated as config — never logged either."""

    api_key: SecretApiKey
    voice_id: str


def load_cartesia_credentials() -> CartesiaCredentials:
    """Resolve credentials (DPAPI store first, env fallback), fail closed.

    Raises :class:`VoiceNotConfiguredError` naming the missing variable —
    never a default, never a guess, never an echo of any present value.
    """
    # DPAPI-store-first, env fallback — the exact precedence every other
    # provider key follows (a key the user saved in-app beats a stale env).
    stored_key = ProviderKeyStore().get_key("cartesia")
    if stored_key is None:
        raise VoiceNotConfiguredError(
            f"{CARTESIA_API_KEY_ENV_VAR} is not set; Naomi's voice needs a Cartesia key."
        )
    voice_id = os.environ.get(CARTESIA_VOICE_ID_ENV_VAR, "").strip()
    if not voice_id:
        raise VoiceNotConfiguredError(
            f"{CARTESIA_VOICE_ID_ENV_VAR} is not set; Naomi's voice needs a Cartesia voice."
        )
    return CartesiaCredentials(api_key=stored_key, voice_id=voice_id)
