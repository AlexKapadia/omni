"""Per-session transcript event emitter: persists finals and broadcasts to the UI.

Purpose: owns the presentation/persistence tail of the live pipeline — turns
per-stream word tokens into ``transcript.partial`` / ``transcript.final``
events, persists final segments, and tracks finalisation latency (the speed
showcase). One instance per capture session, created by
``LiveCaptureService.start`` and discarded at ``stop``.
Pipeline position: below ``engine.stt.live_capture_service`` (session
orchestration), above ``engine.storage`` and the broadcast hub.

Security / fidelity invariants:
- Final text is persisted VERBATIM (fidelity mandate): the space-join is
  presentation; the tokens are ground truth and are never rewritten here.
- Parameterised SQL only (via the segments repository).
"""

import time
import uuid

import aiosqlite

from engine.audio.audio_frame_types import StreamLabel
from engine.protocol.capture_event_payloads import (
    EVENT_TRANSCRIPT_FINAL,
    EVENT_TRANSCRIPT_PARTIAL,
    build_transcript_final_payload,
    build_transcript_partial_payload,
)
from engine.protocol.event_broadcast_hub import EventBroadcastHub
from engine.storage.meetings_repository import utc_now_iso
from engine.storage.transcript_segments_repository import insert_transcript_segment
from engine.stt.transcription_latency_tracker import TranscriptionLatencyTracker
from engine.stt.word_token_types import WordToken


class TranscriptEventEmitter:
    """Emits transcript events for exactly one capture session."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        connection: aiosqlite.Connection,
        meeting_id: str,
        anchor_monotonic: float,
    ) -> None:
        self._hub = hub
        self._connection = connection
        self._meeting_id = meeting_id
        self._anchor_monotonic = anchor_monotonic
        self._sequence_counters: dict[str, int] = {}
        self._latency = TranscriptionLatencyTracker()
        # Speech clock for the silence auto-stop monitor: session start counts
        # as activity so a fully-silent meeting still times out from t=0.
        self._last_activity_monotonic = time.monotonic()

    @property
    def last_activity_monotonic(self) -> float:
        """Monotonic time of the last emitted speech (or session start)."""
        return self._last_activity_monotonic

    def _next_seq(self, stream: str) -> int:
        self._sequence_counters[stream] = self._sequence_counters.get(stream, 0) + 1
        return self._sequence_counters[stream]

    def log_latency_summary(self) -> None:
        """Speed showcase: p50/p95 finalisation lag into the log."""
        self._latency.log_summary()

    async def emit_partial(self, label: StreamLabel, words: list[WordToken]) -> None:
        self._last_activity_monotonic = time.monotonic()  # speech resets silence
        await self._hub.broadcast_event(
            EVENT_TRANSCRIPT_PARTIAL,
            build_transcript_partial_payload(
                stream=label.value,
                # Space-joined verbatim tokens — the join is presentation,
                # the tokens are ground truth (fidelity mandate).
                text=" ".join(w.text for w in words),
                t_start=words[0].t_start,
                t_end=words[-1].t_end,
                seq=self._next_seq(label.value),
            ),
        )

    async def emit_final(self, label: StreamLabel, words: list[WordToken]) -> None:
        self._last_activity_monotonic = time.monotonic()  # speech resets silence
        segment_id = str(uuid.uuid4())
        text = " ".join(w.text for w in words)
        t_start, t_end = words[0].t_start, words[-1].t_end
        await insert_transcript_segment(
            self._connection,
            segment_id=segment_id,
            meeting_id=self._meeting_id,
            stream=label.value,
            text=text,  # Verbatim (fidelity mandate).
            t_start=t_start,
            t_end=t_end,
            created_at_iso=utc_now_iso(),
        )
        # lag = audio-end -> emit, on the shared monotonic clock. max(0)
        # guards sub-ms scheduling skew from ever reporting negative time.
        lag_ms = max(0.0, (time.monotonic() - (self._anchor_monotonic + t_end)) * 1000.0)
        self._latency.record(lag_ms)
        await self._hub.broadcast_event(
            EVENT_TRANSCRIPT_FINAL,
            build_transcript_final_payload(
                stream=label.value,
                text=text,
                t_start=t_start,
                t_end=t_end,
                seq=self._next_seq(label.value),
                segment_id=segment_id,
                lag_ms=lag_ms,
            ),
        )
