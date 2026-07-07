"""Cartesia WebSocket message framing: exact request/response shapes.

Purpose: pure functions building the OUTBOUND generation/cancel frames and
parsing the INBOUND stream messages, per the Cartesia TTS WebSocket API
(docs.cartesia.ai/api-reference/tts/websocket — see
docs/research/naomi/cartesia-sonic-realtime-tts/). Keeping the framing pure
makes the protocol exactly testable with zero network.
Pipeline position: used only by ``cartesia_streaming_tts_client``.

Security invariant: inbound provider messages are UNTRUSTED input — the
parser is fail-closed (None on any deviation) and bounds what it accepts;
a hostile frame can be dropped but never crash the stream loop.
"""

import json
from dataclasses import dataclass

# Endpoint + version (research: required query param cartesia_version).
CARTESIA_WSS_URL = "wss://api.cartesia.ai/tts/websocket"
CARTESIA_API_VERSION = "2026-03-01"
# Pinned snapshot per the brief §7 (production recommendation) — never
# a floating "latest" in a shipped path.
CARTESIA_MODEL_ID = "sonic-3.5-2026-05-04"
# pcm_f32le @ 24kHz: zero-conversion feed into the UI's Web Audio graph.
CARTESIA_OUTPUT_SAMPLE_RATE = 24000

# Hard cap on one inbound provider frame (audio chunks are ~KB-scale; a
# multi-MB frame is a fault or an attack — resource-exhaustion defence).
_MAX_PROVIDER_FRAME_BYTES = 4 * 1024 * 1024


def quantize_affect_to_cartesia_emotion(valence: float, arousal: float) -> str:
    """(v, a) → Cartesia generation_config.emotion, per the brief §3.

    Deterministic boundaries (tested on/over/under): positive valence reads
    "content", negative splits "angry"/"sad" on arousal, low-arousal
    neutral valence reads "calm", everything else "neutral".
    """
    if valence >= 0.35:
        return "content"
    if valence <= -0.35:
        return "angry" if arousal >= 0.5 else "sad"
    if arousal < 0.25:
        return "calm"
    return "neutral"


def speed_from_arousal(arousal: float) -> float:
    """Brief §3: speed = 0.9 + 0.25·a, clamped into Cartesia's 0.6-1.5."""
    clamped_arousal = min(1.0, max(0.0, arousal))
    return min(1.5, max(0.6, 0.9 + 0.25 * clamped_arousal))


def build_generation_request(
    text: str,
    context_id: str,
    voice_id: str,
    affect: tuple[float, float] | None,
    *,
    continue_transcript: bool = False,
) -> str:
    """One generation frame. ``continue_transcript=True`` marks a NON-FINAL
    input chunk on a multiplexed context (Cartesia input streaming: the turn
    orchestrator sends clause chunks with continue=true and the LAST chunk
    with continue=false, per the docs' continuation contract). The default
    (False) is the single-shot shape the dev naomi.say path keeps using.
    Word timestamps ON — they drive the caption and word-rate pulses."""
    request: dict[str, object] = {
        "model_id": CARTESIA_MODEL_ID,
        "transcript": text,
        "context_id": context_id,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "raw",
            "encoding": "pcm_f32le",
            "sample_rate": CARTESIA_OUTPUT_SAMPLE_RATE,
        },
        "add_timestamps": True,
        "continue": continue_transcript,
        "language": "en",
    }
    if affect is not None:
        valence, arousal = affect
        request["generation_config"] = {
            "emotion": quantize_affect_to_cartesia_emotion(valence, arousal),
            "speed": speed_from_arousal(arousal),
        }
    return json.dumps(request, separators=(",", ":"))


def build_cancel_request(context_id: str) -> str:
    """The barge-in primitive: stop generation for one context."""
    return json.dumps({"context_id": context_id, "cancel": True}, separators=(",", ":"))


# ---- Inbound message taxonomy (fail-closed parse) -------------------------


@dataclass(frozen=True)
class CartesiaAudioChunk:
    context_id: str
    data_b64: str


@dataclass(frozen=True)
class CartesiaWordTimestamps:
    context_id: str
    words: tuple[str, ...]
    starts_s: tuple[float, ...]
    ends_s: tuple[float, ...]


@dataclass(frozen=True)
class CartesiaDone:
    context_id: str


@dataclass(frozen=True)
class CartesiaErrorMessage:
    context_id: str
    message: str


CartesiaMessage = CartesiaAudioChunk | CartesiaWordTimestamps | CartesiaDone | CartesiaErrorMessage


def parse_cartesia_message(raw: str | bytes) -> CartesiaMessage | None:
    """Parse one inbound provider frame; None on anything unusable.

    Deny-by-default: unknown types, wrong field types, oversized frames and
    misaligned timestamp arrays are all dropped, never half-applied.
    """
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if size > _MAX_PROVIDER_FRAME_BYTES:
        return None
    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    context_id = decoded.get("context_id")
    if not isinstance(context_id, str) or not context_id:
        return None
    message_type = decoded.get("type")
    if message_type == "chunk":
        data = decoded.get("data")
        if not isinstance(data, str) or not data:
            return None
        return CartesiaAudioChunk(context_id=context_id, data_b64=data)
    if message_type == "timestamps":
        stamps = decoded.get("word_timestamps")
        if not isinstance(stamps, dict):
            return None
        words = stamps.get("words")
        starts = stamps.get("start")
        ends = stamps.get("end")
        if not (isinstance(words, list) and isinstance(starts, list) and isinstance(ends, list)):
            return None
        if not (len(words) == len(starts) == len(ends)):
            return None  # misaligned arrays: corrupt, refuse whole frame
        if not all(isinstance(w, str) for w in words):
            return None
        if not all(isinstance(s, int | float) and s >= 0 for s in starts + ends):
            return None
        return CartesiaWordTimestamps(
            context_id=context_id,
            words=tuple(words),
            starts_s=tuple(float(s) for s in starts),
            ends_s=tuple(float(e) for e in ends),
        )
    if message_type == "done":
        return CartesiaDone(context_id=context_id)
    if message_type == "error":
        error_text = decoded.get("error")
        message = error_text if isinstance(error_text, str) else "provider reported an error"
        return CartesiaErrorMessage(context_id=context_id, message=message)
    return None  # unknown type — deny by default
