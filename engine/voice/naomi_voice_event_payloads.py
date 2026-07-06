"""Naomi voice wire shapes: event names, payload builders, command models.

Purpose: the ADDITIVE naomi.* surface on WS protocol v1 — documented here as
the single source of truth the UI mirrors (apps/ui/src/naomi/naomi-voice-protocol.ts).

Events (engine → UI):
- ``naomi.audio.chunk``        {context_id, seq, pcm_b64, sample_rate, ttfa_ms?}
  pcm_b64 is base64 pcm_f32le @ 24kHz; ttfa_ms rides ONLY on seq 0 (the
  honest, measured time-to-first-audio for the utterance).
- ``naomi.audio.done``         {context_id, reason: completed|cancelled|error, detail?}
- ``naomi.speaking.timestamps`` {context_id, words[], starts_s[], ends_s[]}

Commands (UI → engine):
- ``naomi.say``    {text, affect?: {v, a, burst?}}
- ``naomi.cancel`` {}

Security invariant: command payloads are untrusted input — pydantic strict
models with extra="forbid" and hard bounds (deny by default).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from engine.voice.cartesia_message_framing import CARTESIA_OUTPUT_SAMPLE_RATE

EVENT_NAOMI_AUDIO_CHUNK = "naomi.audio.chunk"
EVENT_NAOMI_AUDIO_DONE = "naomi.audio.done"
EVENT_NAOMI_SPEAKING_TIMESTAMPS = "naomi.speaking.timestamps"
COMMAND_NAOMI_SAY = "naomi.say"
COMMAND_NAOMI_CANCEL = "naomi.cancel"

# Text bound: a spoken reply is sentences, not documents; anything larger is
# a bug or abuse (and must stay far under the 64KiB frame cap).
_MAX_SAY_TEXT_LENGTH = 2000


class NaomiAffectPayload(BaseModel):
    """The (valence, arousal, burst) triple as it rides naomi.say."""

    model_config = ConfigDict(extra="forbid")

    v: float = Field(ge=-1, le=1)
    a: float = Field(ge=0, le=1)
    burst: Literal["laugh"] | None = None


class NaomiSayCommandPayload(BaseModel):
    """naomi.say — text is untrusted user/dev input, hard-bounded."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=_MAX_SAY_TEXT_LENGTH)
    affect: NaomiAffectPayload | None = None


class NaomiCancelCommandPayload(BaseModel):
    """naomi.cancel carries nothing; extra fields are rejected."""

    model_config = ConfigDict(extra="forbid")


def build_naomi_audio_chunk_payload(
    context_id: str,
    seq: int,
    pcm_b64: str,
    ttfa_ms: float | None,
) -> dict[str, object]:
    """One relayed audio chunk. ttfa_ms is present only when measured (seq 0)."""
    payload: dict[str, object] = {
        "context_id": context_id,
        "seq": seq,
        "pcm_b64": pcm_b64,
        "sample_rate": CARTESIA_OUTPUT_SAMPLE_RATE,
    }
    if ttfa_ms is not None:
        payload["ttfa_ms"] = ttfa_ms
    return payload


def build_naomi_audio_done_payload(
    context_id: str,
    reason: Literal["completed", "cancelled", "error"],
    detail: str | None = None,
) -> dict[str, object]:
    """Utterance end. detail (bounded) only accompanies reason="error"."""
    payload: dict[str, object] = {"context_id": context_id, "reason": reason}
    if detail is not None:
        # Provider error text is untrusted — bound what we reflect to the UI.
        payload["detail"] = detail[:200]
    return payload


def build_naomi_speaking_timestamps_payload(
    context_id: str,
    words: tuple[str, ...],
    starts_s: tuple[float, ...],
    ends_s: tuple[float, ...],
) -> dict[str, object]:
    """Word-level timing for the caption highlight and word-rate pulses."""
    return {
        "context_id": context_id,
        "words": list(words),
        "starts_s": list(starts_s),
        "ends_s": list(ends_s),
    }
