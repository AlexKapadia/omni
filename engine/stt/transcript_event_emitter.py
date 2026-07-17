"""Per-session transcript event emitter: persists finals and broadcasts to the UI."""

import time
import uuid

import aiosqlite
import numpy as np
import numpy.typing as npt

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
from engine.stt.speaker_voice_profile import SpeakerSessionLabeler
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
        speaker_labeler: SpeakerSessionLabeler | None = None,
    ) -> None:
        self._hub = hub
        self._connection = connection
        self._meeting_id = meeting_id
        self._anchor_monotonic = anchor_monotonic
        self._labeler = speaker_labeler
        self._sequence_counters: dict[str, int] = {}
        self._latency = TranscriptionLatencyTracker()
        self._last_activity_monotonic = time.monotonic()

    @property
    def last_activity_monotonic(self) -> float:
        return self._last_activity_monotonic

    def _next_seq(self, stream: str) -> int:
        self._sequence_counters[stream] = self._sequence_counters.get(stream, 0) + 1
        return self._sequence_counters[stream]

    def log_latency_summary(self) -> None:
        self._latency.log_summary()

    def _labels_for_partial(
        self, label: StreamLabel, active_speaker_id: str | None
    ) -> tuple[str, str]:
        if self._labeler is None:
            speaker_id = "me" if label is StreamLabel.ME else "1"
            display = "Me" if label is StreamLabel.ME else "Them"
            return (speaker_id, display)
        if label is StreamLabel.ME:
            return self._labeler.me_labels()
        return self._labeler.them_partial_label(active_speaker_id)

    def _labels_for_final(
        self, label: StreamLabel, audio: npt.NDArray[np.float32]
    ) -> tuple[str, str]:
        if self._labeler is None:
            speaker_id = "me" if label is StreamLabel.ME else "1"
            display = "Me" if label is StreamLabel.ME else "Them"
            return (speaker_id, display)
        if label is StreamLabel.ME:
            return self._labeler.me_labels()
        return self._labeler.assign_them(audio)

    async def emit_partial(
        self,
        label: StreamLabel,
        words: list[WordToken],
        *,
        active_speaker_id: str | None = None,
    ) -> None:
        self._last_activity_monotonic = time.monotonic()
        speaker_id, speaker_label = self._labels_for_partial(label, active_speaker_id)
        await self._hub.broadcast_event(
            EVENT_TRANSCRIPT_PARTIAL,
            build_transcript_partial_payload(
                stream=label.value,
                text=" ".join(w.text for w in words),
                t_start=words[0].t_start,
                t_end=words[-1].t_end,
                seq=self._next_seq(label.value),
                speaker_id=speaker_id,
                speaker_label=speaker_label,
            ),
        )

    async def emit_final(
        self,
        label: StreamLabel,
        words: list[WordToken],
        *,
        audio: npt.NDArray[np.float32],
    ) -> None:
        self._last_activity_monotonic = time.monotonic()
        segment_id = str(uuid.uuid4())
        text = " ".join(w.text for w in words)
        t_start, t_end = words[0].t_start, words[-1].t_end
        speaker_id, speaker_label = self._labels_for_final(label, audio)
        await insert_transcript_segment(
            self._connection,
            segment_id=segment_id,
            meeting_id=self._meeting_id,
            stream=label.value,
            speaker_id=speaker_id,
            text=text,
            t_start=t_start,
            t_end=t_end,
            created_at_iso=utc_now_iso(),
        )
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
                speaker_id=speaker_id,
                speaker_label=speaker_label,
            ),
        )
