"""Cartesia credential resolution: env vars → SecretApiKey + voice id.

Purpose: the ONLY place Cartesia credentials are read. CARTESIA_API_KEY and
CARTESIA_VOICE_ID come from the process environment (populated by the DEV
RUNNER from .env, or by the packaged app's DPAPI store once Cartesia joins
the onboarding key flow — engine code NEVER reads .env directly, matching
``engine.security.provider_key_store``).
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
    """Resolve credentials from the process environment, fail closed.

    Raises :class:`VoiceNotConfiguredError` naming the missing variable —
    never a default, never a guess, never an echo of any present value.
    """
    raw_key = os.environ.get(CARTESIA_API_KEY_ENV_VAR, "").strip()
    if not raw_key:
        raise VoiceNotConfiguredError(
            f"{CARTESIA_API_KEY_ENV_VAR} is not set; Naomi's voice needs a Cartesia key."
        )
    voice_id = os.environ.get(CARTESIA_VOICE_ID_ENV_VAR, "").strip()
    if not voice_id:
        raise VoiceNotConfiguredError(
            f"{CARTESIA_VOICE_ID_ENV_VAR} is not set; Naomi's voice needs a Cartesia voice."
        )
    return CartesiaCredentials(api_key=SecretApiKey(raw_key), voice_id=voice_id)
