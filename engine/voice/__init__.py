"""Omni engine voice package: Naomi's realtime TTS pipeline (Cartesia).

Purpose: everything between "the agent has words to say" and "PCM + word
timestamps are streaming to the UI" — the Cartesia WebSocket client, the
playback streamer that relays audio over the engine's event hub, and the
naomi.* command surface.
Pipeline position: downstream of the router/agents (which produce text +
affect), upstream of the UI's Web Audio playout. Egress-bearing: every
external call is gated by the kill switch (engine.security) BEFORE any
connection is attempted.

Security invariants (claude.md §5.6 project bindings):
- CARTESIA_API_KEY travels only as SecretApiKey; never logged, redacted
  from every error string (same discipline as engine.router clients).
- Kill switch engaged => no Cartesia connection is ever opened (fail
  closed on egress; the visual stays alive — it is fully local).
- Transcript/text content sent to Cartesia is the minimum the task needs.
"""

from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient
from engine.voice.naomi_voice_command_dispatcher import (
    NAOMI_COMMAND_NAMES,
    dispatch_naomi_command,
)
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer
from engine.voice.voice_errors import (
    VoiceEgressBlockedError,
    VoiceNotConfiguredError,
    VoiceProviderError,
)

__all__ = [
    "NAOMI_COMMAND_NAMES",
    "CartesiaStreamingTtsClient",
    "TtsPlaybackStreamer",
    "VoiceEgressBlockedError",
    "VoiceNotConfiguredError",
    "VoiceProviderError",
    "dispatch_naomi_command",
]
