"""Cartesia key custody: the API key can never appear in any error, log
record, repr, or broadcast payload — no matter which layer fails.

Security invariant under test (claude.md §5.6): secrets never in logs or
errors. The fake transports here deliberately EMBED the key in their
exception text (the way an HTTP client echoing headers would) and the
tests prove it comes out [REDACTED] everywhere.
"""

import asyncio
import logging

import pytest

from engine.protocol import Envelope, EventBroadcastHub
from engine.security import REDACTION_PLACEHOLDER, SecretApiKey
from engine.voice.cartesia_credentials import (
    CARTESIA_API_KEY_ENV_VAR,
    CARTESIA_VOICE_ID_ENV_VAR,
    CartesiaCredentials,
    load_cartesia_credentials,
)
from engine.voice.cartesia_streaming_tts_client import (
    CartesiaStreamingTtsClient,
    WsConnectionLike,
)
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer
from engine.voice.voice_errors import VoiceNotConfiguredError, VoiceProviderError

FAKE_KEY = "sk-car-SUPER-SECRET-0123456789abcdef"
CREDS = CartesiaCredentials(api_key=SecretApiKey(FAKE_KEY), voice_id="voice-abc")


class LeakyConnect:
    """A connect that fails echoing the key — like an SDK echoing headers."""

    async def __call__(self) -> WsConnectionLike:
        raise ConnectionError(f"401 unauthorized for X-API-Key: {FAKE_KEY}")


class LeakyRecvWs:
    """A socket whose recv fails with the key embedded in the message."""

    async def send(self, data: str) -> None:
        return None

    async def recv(self) -> str | bytes:
        raise ConnectionError(f"stream torn; last request used key {FAKE_KEY}")

    async def close(self) -> None:
        return None


async def test_connect_failure_error_is_redacted() -> None:
    client = CartesiaStreamingTtsClient(CREDS, connect_factory=LeakyConnect())
    with pytest.raises(VoiceProviderError) as excinfo:
        async for _ in client.stream_utterance("Hi", "ctx", None):
            pass
    message = str(excinfo.value)
    assert FAKE_KEY not in message
    assert REDACTION_PLACEHOLDER in message
    # The chain is severed too — no __cause__ can resurrect the raw text.
    assert excinfo.value.__cause__ is None


async def test_stream_failure_error_is_redacted() -> None:
    async def connect() -> WsConnectionLike:
        return LeakyRecvWs()

    client = CartesiaStreamingTtsClient(CREDS, connect_factory=connect)
    with pytest.raises(VoiceProviderError) as excinfo:
        async for _ in client.stream_utterance("Hi", "ctx", None):
            pass
    assert FAKE_KEY not in str(excinfo.value)
    assert REDACTION_PLACEHOLDER in str(excinfo.value)


async def test_streamer_broadcast_error_payload_never_contains_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure travels client → streamer → hub broadcast → (UI). The key
    must be absent from the WHOLE broadcast envelope and all logs."""
    client = CartesiaStreamingTtsClient(CREDS, connect_factory=LeakyConnect())
    hub = EventBroadcastHub()
    broadcasts: list[Envelope] = []

    async def collect(envelope: Envelope) -> None:
        broadcasts.append(envelope)

    hub.subscribe(collect)
    streamer = TtsPlaybackStreamer(hub, client_factory=lambda: client)
    with caplog.at_level(logging.DEBUG):
        await streamer.say("Hello", None)
        # Drain the relay task to completion.
        for _ in range(50):
            if streamer.active_context_id is None:
                break
            await asyncio.sleep(0)
    done_events = [b for b in broadcasts if b.name == "naomi.audio.done"]
    assert len(done_events) == 1
    assert done_events[0].payload["reason"] == "error"
    assert FAKE_KEY not in done_events[0].to_wire()
    assert FAKE_KEY not in caplog.text  # nothing logged the key either


def test_missing_credentials_error_names_the_variable_never_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CARTESIA_API_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(CARTESIA_VOICE_ID_ENV_VAR, raising=False)
    with pytest.raises(VoiceNotConfiguredError) as excinfo:
        load_cartesia_credentials()
    assert CARTESIA_API_KEY_ENV_VAR in str(excinfo.value)


def test_missing_voice_id_still_never_echoes_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CARTESIA_API_KEY_ENV_VAR, FAKE_KEY)
    monkeypatch.delenv(CARTESIA_VOICE_ID_ENV_VAR, raising=False)
    with pytest.raises(VoiceNotConfiguredError) as excinfo:
        load_cartesia_credentials()
    assert FAKE_KEY not in str(excinfo.value)
    assert CARTESIA_VOICE_ID_ENV_VAR in str(excinfo.value)


def test_loaded_credentials_wrap_the_key_in_a_redacting_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CARTESIA_API_KEY_ENV_VAR, FAKE_KEY)
    monkeypatch.setenv(CARTESIA_VOICE_ID_ENV_VAR, "voice-x")
    creds = load_cartesia_credentials()
    assert FAKE_KEY not in repr(creds)  # dataclass repr shows SecretApiKey([REDACTED])
    assert FAKE_KEY not in str(creds.api_key)
    assert creds.api_key.reveal() == FAKE_KEY  # the single sanctioned door
