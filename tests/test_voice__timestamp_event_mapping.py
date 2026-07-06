"""Cartesia stream → naomi.* event mapping: chunk sequencing, the honest
TTFA measurement on seq 0 ONLY, word-timestamp relay, and completion/error
done events — payload-exact against the documented wire shapes.
"""

import asyncio
from collections.abc import AsyncIterator

from engine.protocol import Envelope, EventBroadcastHub
from engine.security import SecretApiKey
from engine.voice.cartesia_credentials import CartesiaCredentials
from engine.voice.cartesia_message_framing import (
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaMessage,
    CartesiaWordTimestamps,
)
from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer

CREDS = CartesiaCredentials(
    api_key=SecretApiKey("sk-car-test-0123456789abcdef"), voice_id="voice-abc"
)


class ScriptedClient(CartesiaStreamingTtsClient):
    """Replays a fixed message script for whatever context asks."""

    def __init__(self, script: list[CartesiaMessage]) -> None:
        super().__init__(CREDS, connect_factory=None)
        self._script = script

    async def stream_utterance(
        self, text: str, context_id: str, affect: tuple[float, float] | None
    ) -> AsyncIterator[CartesiaMessage]:
        for message in self._script:
            # Rewrite the scripted context to the real one (the streamer
            # generates a fresh uuid per say).
            if isinstance(message, CartesiaAudioChunk):
                yield CartesiaAudioChunk(context_id=context_id, data_b64=message.data_b64)
            elif isinstance(message, CartesiaWordTimestamps):
                yield CartesiaWordTimestamps(
                    context_id=context_id,
                    words=message.words,
                    starts_s=message.starts_s,
                    ends_s=message.ends_s,
                )
            elif isinstance(message, CartesiaDone):
                yield CartesiaDone(context_id=context_id)
            else:
                yield CartesiaErrorMessage(context_id=context_id, message="scripted failure")


class SteppingClock:
    """Deterministic monotonic clock: +50ms per reading."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        current = self.now
        self.now += 0.050
        return current


async def run_streamer(script: list[CartesiaMessage]) -> tuple[str, list[Envelope]]:
    hub = EventBroadcastHub()
    seen: list[Envelope] = []

    async def collector(envelope: Envelope) -> None:
        seen.append(envelope)

    hub.subscribe(collector)
    streamer = TtsPlaybackStreamer(
        hub, client_factory=lambda: ScriptedClient(script), clock=SteppingClock()
    )
    context_id = await streamer.say("Hello world", (0.5, 0.5))
    for _ in range(100):  # drain the relay task
        if streamer.active_context_id is None:
            break
        await asyncio.sleep(0)
    return context_id, seen


async def test_chunks_relay_in_order_with_ttfa_on_seq_zero_only() -> None:
    context_id, seen = await run_streamer(
        [
            CartesiaAudioChunk(context_id="s", data_b64="QQ=="),
            CartesiaAudioChunk(context_id="s", data_b64="Qg=="),
            CartesiaAudioChunk(context_id="s", data_b64="Qw=="),
            CartesiaDone(context_id="s"),
        ]
    )
    chunks = [e for e in seen if e.name == "naomi.audio.chunk"]
    assert [c.payload["seq"] for c in chunks] == [0, 1, 2]
    assert [c.payload["pcm_b64"] for c in chunks] == ["QQ==", "Qg==", "Qw=="]
    assert all(c.payload["sample_rate"] == 24000 for c in chunks)
    assert all(c.payload["context_id"] == context_id for c in chunks)
    # TTFA: clock steps 50ms per read; dispatch read then first-chunk read
    # → 50ms (to float64 representation), present ONLY on seq 0.
    ttfa = chunks[0].payload["ttfa_ms"]
    assert isinstance(ttfa, float)
    assert abs(ttfa - 50.0) < 1e-9
    assert "ttfa_ms" not in chunks[1].payload
    assert "ttfa_ms" not in chunks[2].payload


async def test_word_timestamps_map_to_the_documented_payload_shape() -> None:
    context_id, seen = await run_streamer(
        [
            CartesiaWordTimestamps(
                context_id="s",
                words=("water", "moves"),
                starts_s=(0.0, 0.42),
                ends_s=(0.4, 0.85),
            ),
            CartesiaDone(context_id="s"),
        ]
    )
    stamps = [e for e in seen if e.name == "naomi.speaking.timestamps"]
    assert len(stamps) == 1
    assert stamps[0].payload == {
        "context_id": context_id,
        "words": ["water", "moves"],
        "starts_s": [0.0, 0.42],
        "ends_s": [0.4, 0.85],
    }


async def test_done_maps_to_completed() -> None:
    context_id, seen = await run_streamer([CartesiaDone(context_id="s")])
    done = [e for e in seen if e.name == "naomi.audio.done"]
    assert len(done) == 1
    assert done[0].payload == {"context_id": context_id, "reason": "completed"}


async def test_provider_error_maps_to_done_error_with_bounded_detail() -> None:
    context_id, seen = await run_streamer(
        [CartesiaErrorMessage(context_id="s", message="ignored-by-script")]
    )
    done = [e for e in seen if e.name == "naomi.audio.done"]
    assert len(done) == 1
    assert done[0].payload["reason"] == "error"
    assert done[0].payload["context_id"] == context_id
    detail = done[0].payload["detail"]
    assert isinstance(detail, str) and len(detail) <= 200  # untrusted text bounded


async def test_every_broadcast_rides_a_valid_v1_event_envelope() -> None:
    _, seen = await run_streamer(
        [CartesiaAudioChunk(context_id="s", data_b64="QQ=="), CartesiaDone(context_id="s")]
    )
    for envelope in seen:
        assert envelope.v == 1
        assert envelope.kind.value == "event"
        assert envelope.name.startswith("naomi.")
        assert isinstance(envelope.payload, dict)
