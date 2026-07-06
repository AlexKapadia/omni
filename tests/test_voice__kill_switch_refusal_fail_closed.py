"""Voice kill-switch tests: engaged means ZERO Cartesia egress, fail closed.

Security invariant under test (claude.md §5.6 project binding + the brief's
security bindings): the kill switch halts Cartesia like any other external
call — BEFORE any connection is attempted, at BOTH layers (streamer and
client — defence in depth), for garbled flag values too, and the refusal is
an honest structured error all the way to the WS surface.
"""

from collections.abc import Iterator

import pytest

from engine.protocol import EventBroadcastHub
from engine.security import SecretApiKey
from engine.security.kill_switch import (
    KILL_SWITCH_ENV_VAR,
    set_kill_switch_runtime_override,
)
from engine.voice.cartesia_credentials import CartesiaCredentials
from engine.voice.cartesia_streaming_tts_client import (
    CartesiaStreamingTtsClient,
    WsConnectionLike,
)
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer
from engine.voice.voice_errors import VoiceEgressBlockedError

CREDS = CartesiaCredentials(
    api_key=SecretApiKey("sk-car-test-0123456789abcdef"), voice_id="voice-abc"
)


@pytest.fixture(autouse=True)
def _clean_kill_switch_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts disengaged: env unset, runtime override cleared."""
    monkeypatch.delenv(KILL_SWITCH_ENV_VAR, raising=False)
    set_kill_switch_runtime_override(None)
    yield
    set_kill_switch_runtime_override(None)


class ConnectCounter:
    """Fails the suite loudly if the client ever tries to connect."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> WsConnectionLike:
        self.calls += 1
        raise AssertionError("kill switch engaged but a Cartesia connection was attempted")


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "garbled-nonsense", "2"])
async def test_client_refuses_before_connecting_for_on_and_garbled_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Recognised ON values AND unrecognised garbage both refuse (deny by
    default on the security control itself)."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, value)
    counter = ConnectCounter()
    client = CartesiaStreamingTtsClient(CREDS, connect_factory=counter)
    with pytest.raises(VoiceEgressBlockedError):
        async for _ in client.stream_utterance("Hi", "ctx", None):
            raise AssertionError("no message should ever be yielded")
    assert counter.calls == 0  # zero egress: not even a connection attempt


async def test_runtime_override_refuses_without_restart() -> None:
    set_kill_switch_runtime_override(True)
    counter = ConnectCounter()
    client = CartesiaStreamingTtsClient(CREDS, connect_factory=counter)
    with pytest.raises(VoiceEgressBlockedError):
        async for _ in client.stream_utterance("Hi", "ctx", None):
            pass
    assert counter.calls == 0


async def test_streamer_refuses_before_building_any_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The streamer's own gate fires first: no client, no task, no state."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "1")
    factory_calls = 0

    def factory() -> CartesiaStreamingTtsClient:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("client factory must not run while the switch is engaged")

    streamer = TtsPlaybackStreamer(EventBroadcastHub(), client_factory=factory)
    with pytest.raises(VoiceEgressBlockedError):
        await streamer.say("Hello", None)
    assert factory_calls == 0
    assert streamer.active_context_id is None  # nothing half-started


async def test_refusal_message_is_honest_and_reassuring() -> None:
    """The UI surfaces this verbatim: it must name the switch and say local
    features keep working (the visual stays alive — it is fully local)."""
    set_kill_switch_runtime_override(True)
    streamer = TtsPlaybackStreamer(EventBroadcastHub())
    with pytest.raises(VoiceEgressBlockedError) as excinfo:
        await streamer.say("Hello", None)
    message = str(excinfo.value).lower()
    assert "kill switch" in message
    assert "local" in message


async def test_disengaged_switch_reaches_the_credential_gate_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the switch OFF, say() proceeds to credential resolution —
    proving the refusal above really was the switch."""
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "0")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    monkeypatch.delenv("CARTESIA_VOICE_ID", raising=False)
    from engine.voice.voice_errors import VoiceNotConfiguredError

    streamer = TtsPlaybackStreamer(EventBroadcastHub())
    with pytest.raises(VoiceNotConfiguredError):
        await streamer.say("Hello", None)
