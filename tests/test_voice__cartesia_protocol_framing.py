"""Cartesia WS protocol framing: exact outbound frames, fail-closed inbound
parsing, and a full utterance streamed through a fake (zero-network) socket.

The wire shapes here are the contract with a paid external API — a single
wrong field name silently buys nothing, so every field is asserted exactly
(model pinned, pcm_f32le@24k, add_timestamps, continue=false, voice mode/id).
"""

import json

import pytest

from engine.security import SecretApiKey
from engine.voice.cartesia_credentials import CartesiaCredentials
from engine.voice.cartesia_message_framing import (
    CARTESIA_MODEL_ID,
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaWordTimestamps,
    build_cancel_request,
    build_generation_request,
    parse_cartesia_message,
    quantize_affect_to_cartesia_emotion,
    speed_from_arousal,
)
from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient

CREDS = CartesiaCredentials(
    api_key=SecretApiKey("sk-car-test-0123456789abcdef"), voice_id="voice-abc-123"
)


class FakeWs:
    """Scripted fake WebSocket: records sends, replays queued frames."""

    def __init__(self, scripted: list[str | bytes | Exception]) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._queue = list(scripted)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        if not self._queue:
            raise ConnectionError("fake socket exhausted")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def make_client(ws: FakeWs) -> CartesiaStreamingTtsClient:
    async def connect() -> FakeWs:
        return ws

    return CartesiaStreamingTtsClient(CREDS, connect_factory=connect)


# ---------------------------------------------------------------------------
# Outbound generation frame — field-exact
# ---------------------------------------------------------------------------


def test_generation_request_carries_every_pinned_field_exactly() -> None:
    frame = json.loads(build_generation_request("Hello.", "ctx-1", "voice-abc-123", None))
    assert frame["model_id"] == "sonic-3.5-2026-05-04"  # pinned snapshot, never floating
    assert frame["model_id"] == CARTESIA_MODEL_ID
    assert frame["transcript"] == "Hello."
    assert frame["context_id"] == "ctx-1"
    assert frame["voice"] == {"mode": "id", "id": "voice-abc-123"}
    assert frame["output_format"] == {
        "container": "raw",
        "encoding": "pcm_f32le",
        "sample_rate": 24000,
    }
    assert frame["add_timestamps"] is True
    assert frame["continue"] is False  # last chunk: minimises latency per docs
    assert "generation_config" not in frame  # no affect → provider defaults


def test_generation_request_with_affect_adds_emotion_and_speed() -> None:
    frame = json.loads(build_generation_request("Hi", "c", "v", (0.7, 0.6)))
    assert frame["generation_config"] == {
        "emotion": "content",
        "speed": 0.9 + 0.25 * 0.6,
    }


def test_cancel_request_is_the_documented_barge_in_frame() -> None:
    assert json.loads(build_cancel_request("ctx-9")) == {"context_id": "ctx-9", "cancel": True}


# ---------------------------------------------------------------------------
# Affect → Cartesia emotion quantization (boundary-exact: on / over / under)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valence", "arousal", "expected"),
    [
        (0.35, 0.5, "content"),  # boundary: exactly at the positive cut
        (0.349, 0.5, "neutral"),  # just under
        (1.0, 0.0, "content"),
        (-0.35, 0.5, "angry"),  # boundary: negative + arousal at the cut
        (-0.35, 0.499, "sad"),  # just under the arousal cut → sad
        (-1.0, 1.0, "angry"),
        (-0.349, 0.5, "neutral"),  # just inside the neutral valence band
        (0.0, 0.249, "calm"),  # just under the calm arousal cut
        (0.0, 0.25, "neutral"),  # boundary: exactly at → not calm
        (0.0, 0.5, "neutral"),
    ],
)
def test_emotion_quantization_boundaries(valence: float, arousal: float, expected: str) -> None:
    assert quantize_affect_to_cartesia_emotion(valence, arousal) == expected


@pytest.mark.parametrize(
    ("arousal", "expected"),
    [(0.0, 0.9), (1.0, 1.15), (0.4, 0.9 + 0.25 * 0.4), (-5.0, 0.9), (99.0, 1.15)],
)
def test_speed_formula_exact_and_clamped(arousal: float, expected: float) -> None:
    assert speed_from_arousal(arousal) == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# Inbound parsing — fail closed on everything malformed
# ---------------------------------------------------------------------------


def test_parses_chunk_timestamps_done_and_error_messages() -> None:
    chunk = parse_cartesia_message(json.dumps({"type": "chunk", "context_id": "c", "data": "QUJD"}))
    assert isinstance(chunk, CartesiaAudioChunk) and chunk.data_b64 == "QUJD"
    stamps = parse_cartesia_message(
        json.dumps(
            {
                "type": "timestamps",
                "context_id": "c",
                "word_timestamps": {"words": ["hi", "there"], "start": [0, 0.4], "end": [0.3, 0.9]},
            }
        )
    )
    assert isinstance(stamps, CartesiaWordTimestamps)
    assert stamps.words == ("hi", "there")
    assert stamps.starts_s == (0.0, 0.4)
    done = parse_cartesia_message(json.dumps({"type": "done", "context_id": "c"}))
    assert isinstance(done, CartesiaDone)
    error = parse_cartesia_message(
        json.dumps({"type": "error", "context_id": "c", "error": "boom"})
    )
    assert isinstance(error, CartesiaErrorMessage) and error.message == "boom"


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "[]",
        "42",
        json.dumps({"type": "chunk", "data": "QUJD"}),  # missing context_id
        json.dumps({"type": "chunk", "context_id": "", "data": "QUJD"}),  # empty context
        json.dumps({"type": "chunk", "context_id": "c", "data": ""}),  # empty data
        json.dumps({"type": "chunk", "context_id": "c", "data": 42}),  # wrong type
        json.dumps({"type": "surprise", "context_id": "c"}),  # unknown type
        json.dumps({"type": "timestamps", "context_id": "c", "word_timestamps": "nope"}),
        json.dumps(
            {  # misaligned arrays must be refused whole
                "type": "timestamps",
                "context_id": "c",
                "word_timestamps": {"words": ["a", "b"], "start": [0], "end": [1, 2]},
            }
        ),
        json.dumps(
            {  # negative timestamps are corrupt
                "type": "timestamps",
                "context_id": "c",
                "word_timestamps": {"words": ["a"], "start": [-1], "end": [1]},
            }
        ),
    ],
)
def test_malformed_provider_frames_are_dropped(raw: str) -> None:
    assert parse_cartesia_message(raw) is None


def test_oversized_provider_frame_is_dropped_before_json_decode() -> None:
    huge = '{"type":"chunk","context_id":"c","data":"' + "A" * (5 * 1024 * 1024) + '"}'
    assert parse_cartesia_message(huge) is None


# ---------------------------------------------------------------------------
# A full utterance through the fake socket
# ---------------------------------------------------------------------------


async def test_stream_utterance_sends_request_then_yields_in_order_and_closes() -> None:
    ws = FakeWs(
        [
            json.dumps({"type": "chunk", "context_id": "ctx-1", "data": "QQ=="}),
            json.dumps({"type": "chunk", "context_id": "OTHER", "data": "ZZZZ"}),  # foreign: drop
            "totally corrupt frame",  # malformed: drop, never crash
            json.dumps(
                {
                    "type": "timestamps",
                    "context_id": "ctx-1",
                    "word_timestamps": {"words": ["hi"], "start": [0.0], "end": [0.2]},
                }
            ),
            json.dumps({"type": "done", "context_id": "ctx-1"}),
        ]
    )
    client = make_client(ws)
    received = [m async for m in client.stream_utterance("Hi", "ctx-1", (0.0, 0.1))]
    # The request frame went out first, exactly once.
    assert len(ws.sent) == 1
    sent = json.loads(ws.sent[0])
    assert sent["context_id"] == "ctx-1"
    assert sent["generation_config"]["emotion"] == "calm"  # (0, 0.1) quantized
    # Foreign-context and corrupt frames never surfaced.
    assert [type(m).__name__ for m in received] == [
        "CartesiaAudioChunk",
        "CartesiaWordTimestamps",
        "CartesiaDone",
    ]
    assert ws.closed is True  # connection released after the utterance
