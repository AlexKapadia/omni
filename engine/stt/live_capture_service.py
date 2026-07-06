"""Live capture service: owns capture sessions end-to-end.

Purpose: the single owner of the capture lifecycle — loads the STT models
(readiness for the heartbeat), runs ``capture.start`` / ``capture.stop``,
pumps audio from the ring buffer into the two per-stream pipelines,
persists final segments, and broadcasts every capture/transcript event to
the UI through the broadcast hub.
Pipeline position: the orchestration layer above ``engine.audio`` and the
per-stream pipelines; invoked by the WebSocket command dispatcher.

Security / fidelity invariants:
- Fail closed: capture cannot start unless models are loaded and BOTH
  streams open; a half-capturing session is torn down loudly.
- Audio frames are drained, transcribed, and dropped — never persisted
  (audio-discarded-after-transcription; keep-audio is a later opt-in).
- Final text is persisted verbatim (fidelity mandate) with parameterised
  SQL only.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite
import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import (
    CaptureBackend,
    DualStreamCaptureController,
)
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer
from engine.protocol.capture_event_payloads import (
    EVENT_CAPTURE_DEVICE_CHANGED,
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    EVENT_TRANSCRIPT_PARTIAL,
    build_capture_device_changed_payload,
    build_capture_started_payload,
    build_capture_stopped_payload,
    build_transcript_final_payload,
    build_transcript_partial_payload,
)
from engine.protocol.event_broadcast_hub import EventBroadcastHub
from engine.storage.meetings_repository import insert_meeting, mark_meeting_ended, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import insert_transcript_segment
from engine.stt.model_weights_downloader import SILERO_VAD_FILENAME, models_directory
from engine.stt.parakeet_nemo_transcriber import (
    ParakeetNemoTranscriber,
    stt_dependencies_available,
)
from engine.stt.per_stream_transcription_pipeline import PerStreamTranscriptionPipeline
from engine.stt.silero_onnx_voice_activity_detector import SileroOnnxVoiceActivityDetector
from engine.stt.transcription_latency_tracker import (
    STATS_LOG_INTERVAL_S,
    TranscriptionLatencyTracker,
)
from engine.stt.word_token_types import WordToken

logger = logging.getLogger(__name__)

_DRAIN_INTERVAL_S = 0.05  # Ring-buffer pump cadence: 50 ms keeps latency low.

# Test seams: production defaults are the real hardware/model classes.
VadFactory = Callable[[], Callable[[npt.NDArray[np.float32]], float]]
TranscribeAsyncFn = Callable[[npt.NDArray[np.float32]], Awaitable[list[WordToken]]]


class CaptureServiceError(Exception):
    """User-visible capture failures (already running, models missing...)."""


def _default_backend_factory() -> CaptureBackend:
    from engine.audio.pyaudiowpatch_capture_backend import PyAudioWpatchCaptureBackend

    return PyAudioWpatchCaptureBackend()


def _log_task_crash(task: asyncio.Task[None]) -> None:
    """Done-callback: surface unexpected background-task failures in the log."""
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error("capture background task crashed", exc_info=exception)


class LiveCaptureService:
    """One per engine process. At most one capture session at a time."""

    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        hub: EventBroadcastHub,
        backend_factory: Callable[[], CaptureBackend] = _default_backend_factory,
        models_dir: Path | None = None,
        transcriber: ParakeetNemoTranscriber | None = None,
        vad_factory: VadFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._hub = hub
        self._backend_factory = backend_factory
        self._models_dir = models_dir if models_dir is not None else models_directory()
        self._transcriber = transcriber
        self._vad_factory = vad_factory
        self._stt_ready = False
        self._load_lock = asyncio.Lock()
        # Per-session state (None while idle).
        self._meeting_id: str | None = None
        self._controller: DualStreamCaptureController | None = None
        self._pipelines: dict[StreamLabel, PerStreamTranscriptionPipeline] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._connection: aiosqlite.Connection | None = None  # Open during a session.
        self._anchor_monotonic = 0.0
        self._sequence_counters: dict[str, int] = {}
        self._latency = TranscriptionLatencyTracker()

    @property
    def is_stt_ready(self) -> bool:
        """Heartbeat truth: True only once models are actually loaded."""
        return self._stt_ready

    @property
    def is_capturing(self) -> bool:
        return self._meeting_id is not None

    async def preload_models(self) -> None:
        """Load VAD + Parakeet in the background (idempotent, never raises).

        Called from server startup; failure leaves ``stt_ready`` False —
        honest — and logs why (fail closed, stay up).
        """
        try:
            await self._ensure_models_loaded()
        except Exception:
            logger.exception("STT model preload failed; stt_ready stays false")

    async def start(self, title: str | None) -> str:
        """Begin a capture session; returns the new meeting id."""
        if self._meeting_id is not None:
            raise CaptureServiceError("capture is already running")
        await self._ensure_models_loaded()  # Raises with a clear reason.

        meeting_id = str(uuid.uuid4())
        # Schema first (idempotent), then the session's own connection.
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            await insert_meeting(connection, meeting_id, title or "Untitled meeting", utc_now_iso())
            self._anchor_monotonic = time.monotonic()
            ring_buffer = TimestampedAudioRingBuffer()
            controller = DualStreamCaptureController(
                backend=self._backend_factory(),
                ring_buffer=ring_buffer,
                on_device_changed=self._on_device_changed,
            )
            await controller.start()  # Fail closed: both streams or nothing.
        except Exception as exc:
            await connection.close()
            raise CaptureServiceError(f"could not start capture: {exc}") from exc

        self._connection = connection
        self._controller = controller
        self._meeting_id = meeting_id
        self._sequence_counters = {label.value: 0 for label in StreamLabel}
        self._latency = TranscriptionLatencyTracker()
        self._pipelines = {
            label: self._build_pipeline(label) for label in (StreamLabel.THEM, StreamLabel.ME)
        }
        self._tasks = [
            asyncio.create_task(self._drain_loop(ring_buffer)),
            asyncio.create_task(self._stats_loop()),
        ]
        for task in self._tasks:
            # A crashed pump/stats task must never die silently — the log is
            # the only witness (fail loudly, capture keeps its state honest).
            task.add_done_callback(_log_task_crash)
        await self._hub.broadcast_event(
            EVENT_CAPTURE_STARTED, build_capture_started_payload(meeting_id, "command")
        )
        logger.info("capture started: meeting %s, devices %s", meeting_id, controller.device_names)
        return meeting_id

    async def stop(self) -> str:
        """End the session: flush pipelines, close the meeting, broadcast."""
        meeting_id = self._meeting_id
        if meeting_id is None or self._controller is None or self._connection is None:
            raise CaptureServiceError("capture is not running")
        await self._controller.stop()  # No new audio beyond this point.
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for pipeline in self._pipelines.values():
            await pipeline.finalize()  # Emits any in-flight finals.
        await mark_meeting_ended(self._connection, meeting_id, utc_now_iso())
        await self._connection.close()
        self._latency.log_summary()  # Closing latency report for the session.
        self._connection = None
        self._controller = None
        self._pipelines = {}
        self._tasks = []
        self._meeting_id = None
        await self._hub.broadcast_event(
            EVENT_CAPTURE_STOPPED, build_capture_stopped_payload(meeting_id, "command")
        )
        logger.info("capture stopped: meeting %s", meeting_id)
        return meeting_id

    async def _ensure_models_loaded(self) -> None:
        async with self._load_lock:
            if self._stt_ready:
                return
            if self._vad_factory is None:
                vad_model = self._models_dir / SILERO_VAD_FILENAME
                if not vad_model.is_file():
                    raise CaptureServiceError(f"VAD model missing: {vad_model}")
                self._vad_factory = lambda: SileroOnnxVoiceActivityDetector(vad_model)
            if self._transcriber is None:
                if not stt_dependencies_available():
                    raise CaptureServiceError(
                        "STT dependencies not installed (uv sync --extra stt)"
                    )
                from engine.stt.model_weights_downloader import PARAKEET_FILENAME

                self._transcriber = ParakeetNemoTranscriber(self._models_dir / PARAKEET_FILENAME)
            if not self._transcriber.is_loaded:
                # Heavy load off the event loop; heartbeats keep flowing.
                await asyncio.to_thread(self._transcriber.load)
            self._stt_ready = True

    def _build_pipeline(self, label: StreamLabel) -> PerStreamTranscriptionPipeline:
        assert self._vad_factory is not None and self._transcriber is not None  # noqa: S101
        transcriber = self._transcriber

        async def transcribe(samples: npt.NDArray[np.float32]) -> list[WordToken]:
            return await asyncio.to_thread(transcriber.transcribe_window, samples)

        async def on_partial(words: list[WordToken]) -> None:
            await self._emit_partial(label, words)

        async def on_final(words: list[WordToken], t_open: float, t_close: float) -> None:
            await self._emit_final(label, words, t_close)

        return PerStreamTranscriptionPipeline(
            stream=label,
            anchor_monotonic=self._anchor_monotonic,
            vad_probability=self._vad_factory(),  # Fresh stateful VAD per stream.
            transcribe=transcribe,
            on_partial=on_partial,
            on_final=on_final,
        )

    async def _drain_loop(self, ring_buffer: TimestampedAudioRingBuffer) -> None:
        """Pump frames from callback threads into the pipelines, in order.

        Frames drained here are the last reference to the raw audio — after
        the pipelines consume them they are garbage (discard invariant).
        """
        while True:
            for frame in ring_buffer.drain():
                pipeline = self._pipelines.get(frame.stream)
                if pipeline is not None:
                    await pipeline.feed(frame)
            await asyncio.sleep(_DRAIN_INTERVAL_S)

    async def _stats_loop(self) -> None:
        """Speed showcase: p50/p95 finalisation lag into the log every 60 s."""
        while True:
            await asyncio.sleep(STATS_LOG_INTERVAL_S)
            self._latency.log_summary()

    def _next_seq(self, stream: str) -> int:
        self._sequence_counters[stream] = self._sequence_counters.get(stream, 0) + 1
        return self._sequence_counters[stream]

    async def _emit_partial(self, label: StreamLabel, words: list[WordToken]) -> None:
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

    async def _emit_final(
        self, label: StreamLabel, words: list[WordToken], t_close: float
    ) -> None:
        if self._meeting_id is None or self._connection is None:
            return  # Session tore down mid-flight; nothing to persist onto.
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

    def _on_device_changed(self, label: StreamLabel, device_name: str, recovered_ms: float) -> None:
        """Controller callback (event loop): announce recovery to the UI."""
        asyncio.get_running_loop().create_task(
            self._hub.broadcast_event(
                EVENT_CAPTURE_DEVICE_CHANGED,
                build_capture_device_changed_payload(device_name, recovered_ms),
            )
        )
