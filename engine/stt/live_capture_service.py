"""Live capture service: owns capture sessions end-to-end.

Purpose: the single owner of the capture lifecycle — delegates STT model
loading to ``engine.stt.capture_model_loading`` (readiness for the
heartbeat), runs ``capture.start`` / ``capture.stop``, pumps audio from the
ring buffer into the two per-stream pipelines, persists final segments, and
broadcasts every capture/transcript event to the UI through the broadcast
hub.
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
from engine.audio.stream_echo_canceller import StreamEchoCanceller
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer
from engine.protocol.capture_event_payloads import (
    EVENT_CAPTURE_DEVICE_CHANGED,
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    build_capture_device_changed_payload,
    build_capture_started_payload,
    build_capture_stopped_payload,
)
from engine.protocol.event_broadcast_hub import EventBroadcastHub
from engine.storage.app_settings_repository import SETTING_AEC_ENABLED, read_setting_bool
from engine.storage.meetings_repository import insert_meeting, mark_meeting_ended, utc_now_iso
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.stt.capture_model_loading import (
    CaptureModelLoader,
    CaptureServiceError,
    VadFactory,
)
from engine.stt.keep_audio_recorder import (
    KeepAudioRecorder,
    create_keep_audio_recorder_if_enabled,
)
from engine.stt.loopback_vad_probability_tap import LoopbackVadTap, wrap_vad_with_loopback_tap
from engine.stt.parakeet_nemo_transcriber import ParakeetNemoTranscriber
from engine.stt.per_stream_transcription_pipeline import PerStreamTranscriptionPipeline
from engine.stt.silence_auto_stop_monitor import spawn_silence_auto_stop_tasks
from engine.stt.transcript_event_emitter import TranscriptEventEmitter
from engine.stt.transcription_latency_tracker import STATS_LOG_INTERVAL_S
from engine.stt.word_token_types import WordToken

logger = logging.getLogger(__name__)

_DRAIN_INTERVAL_S = 0.05  # Ring-buffer pump cadence: 50 ms keeps latency low.

# Test seam: production default is the real threaded Parakeet transcribe.
TranscribeAsyncFn = Callable[[npt.NDArray[np.float32]], Awaitable[list[WordToken]]]


def _default_backend_factory() -> CaptureBackend:
    from engine.audio.capture_backend_factory import create_capture_backend

    return create_capture_backend()


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
        silence_timeout_s: float | None = None,
    ) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._hub = hub
        self._backend_factory = backend_factory
        # Model lifecycle lives in its own module (single responsibility).
        self._models = CaptureModelLoader(models_dir, transcriber, vad_factory)
        self._silence_timeout_s = silence_timeout_s  # None → OMNI_AUTOSTOP_SILENCE_S env knob
        # Additive M6 seam (assigned by the server wiring): THEM-stream only.
        self.on_loopback_vad_probability: LoopbackVadTap | None = None
        # Per-session state (None while idle).
        self._meeting_id: str | None = None
        self._controller: DualStreamCaptureController | None = None
        self._pipelines: dict[StreamLabel, PerStreamTranscriptionPipeline] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._connection: aiosqlite.Connection | None = None  # Open during a session.
        self._anchor_monotonic = 0.0
        self._emitter: TranscriptEventEmitter | None = None  # Per-session.
        # Opt-in raw-audio retention (default OFF): None unless the user's
        # keep_audio setting is True for this session (audio-discard default).
        self._keep_audio_recorder: KeepAudioRecorder | None = None

    @property
    def is_stt_ready(self) -> bool:
        """Heartbeat truth: True only once models are actually loaded."""
        return self._models.is_ready

    @property
    def is_capturing(self) -> bool:
        return self._meeting_id is not None

    async def preload_models(self) -> None:
        """Load VAD + Parakeet in the background (idempotent, never raises).

        Called from server startup; failure leaves ``stt_ready`` False —
        honest — and logs why (fail closed, stay up).
        """
        try:
            await self._models.ensure_loaded()
        except Exception:
            logger.exception("STT model preload failed; stt_ready stays false")

    async def start(self, title: str | None) -> str:
        """Begin a capture session; returns the new meeting id."""
        if self._meeting_id is not None:
            raise CaptureServiceError("capture is already running")
        await self._models.ensure_loaded()  # Raises with a clear reason.

        meeting_id = str(uuid.uuid4())
        # Schema first (idempotent), then the session's own connection.
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            await insert_meeting(connection, meeting_id, title or "Untitled meeting", utc_now_iso())
            self._anchor_monotonic = time.monotonic()
            ring_buffer = TimestampedAudioRingBuffer()
            aec_enabled = await read_setting_bool(connection, SETTING_AEC_ENABLED, default=False)
            echo_canceller = StreamEchoCanceller() if aec_enabled else None
            controller = DualStreamCaptureController(
                backend=self._backend_factory(),
                ring_buffer=ring_buffer,
                on_device_changed=self._on_device_changed,
                echo_canceller=echo_canceller,
            )
            await controller.start()  # Fail closed: both streams or nothing.
        except Exception as exc:
            await connection.close()
            raise CaptureServiceError(f"could not start capture: {exc}") from exc

        self._connection = connection
        self._controller = controller
        self._meeting_id = meeting_id
        self._emitter = emitter = TranscriptEventEmitter(
            self._hub, connection, meeting_id, self._anchor_monotonic
        )
        self._pipelines = {
            label: self._build_pipeline(label) for label in (StreamLabel.THEM, StreamLabel.ME)
        }
        # keep-audio opt-in: recorder constructed ONLY when the user's setting
        # is True (default OFF -> None -> audio discarded after transcription).
        self._keep_audio_recorder = await create_keep_audio_recorder_if_enabled(
            connection, meeting_id
        )
        self._tasks = [
            asyncio.create_task(self._drain_loop(ring_buffer)),
            asyncio.create_task(self._stats_loop()),
            *spawn_silence_auto_stop_tasks(  # optional: sustained silence ends the session
                self._silence_timeout_s, lambda: emitter.last_activity_monotonic,
                lambda: self.stop(reason="silence"),
            ),
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

    async def stop(self, reason: str = "command") -> str:
        """End the session; ``reason`` ('command'|'silence'|'error') rides capture.stopped."""
        meeting_id = self._meeting_id
        if meeting_id is None or self._controller is None or self._connection is None:
            raise CaptureServiceError("capture is not running")
        await self._controller.stop()  # No new audio beyond this point.
        current = asyncio.current_task()  # the auto-stop task may be the caller
        for task in self._tasks:
            if task is current:
                continue  # never self-cancel/self-await (would abort this stop)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for pipeline in self._pipelines.values():
            await pipeline.finalize()  # Emits any in-flight finals.
        if self._keep_audio_recorder is not None:
            self._keep_audio_recorder.close()  # finalise WAV headers; no more frames
            self._keep_audio_recorder = None
        await mark_meeting_ended(self._connection, meeting_id, utc_now_iso())
        await self._connection.close()
        if self._emitter is not None:
            self._emitter.log_latency_summary()  # Closing latency report.
        self._emitter = None
        self._connection = None
        self._controller = None
        self._pipelines = {}
        self._tasks = []
        self._meeting_id = None
        await self._hub.broadcast_event(
            EVENT_CAPTURE_STOPPED, build_capture_stopped_payload(meeting_id, reason)
        )
        logger.info("capture stopped: meeting %s (%s)", meeting_id, reason)
        return meeting_id

    def _build_pipeline(self, label: StreamLabel) -> PerStreamTranscriptionPipeline:
        vad_factory = self._models.vad_factory
        transcriber = self._models.transcriber
        assert vad_factory is not None and transcriber is not None  # noqa: S101
        vad_probability = vad_factory()  # Fresh stateful VAD per stream.
        if label is StreamLabel.THEM:
            # Additive detection tap on the loopback stream only (M6 wiring):
            # probabilities, never audio; late-bound; failure-isolated.
            vad_probability = wrap_vad_with_loopback_tap(
                vad_probability, lambda: self.on_loopback_vad_probability
            )

        async def transcribe(samples: npt.NDArray[np.float32]) -> list[WordToken]:
            return await asyncio.to_thread(transcriber.transcribe_window, samples)

        async def on_partial(words: list[WordToken]) -> None:
            emitter = self._emitter
            if emitter is not None:  # Session may tear down mid-flight.
                await emitter.emit_partial(label, words)

        async def on_final(words: list[WordToken], t_open: float, t_close: float) -> None:
            emitter = self._emitter
            if emitter is not None:  # Session may tear down mid-flight.
                await emitter.emit_final(label, words)

        return PerStreamTranscriptionPipeline(
            stream=label,
            anchor_monotonic=self._anchor_monotonic,
            vad_probability=vad_probability,
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
                # keep-audio opt-in: persist BEFORE the pipeline consumes it.
                if self._keep_audio_recorder is not None:
                    self._keep_audio_recorder.write_frame(frame)
                pipeline = self._pipelines.get(frame.stream)
                if pipeline is not None:
                    await pipeline.feed(frame)
            await asyncio.sleep(_DRAIN_INTERVAL_S)

    async def _stats_loop(self) -> None:
        """Speed showcase: p50/p95 finalisation lag into the log every 60 s."""
        while True:
            await asyncio.sleep(STATS_LOG_INTERVAL_S)
            if self._emitter is not None:
                self._emitter.log_latency_summary()

    def _on_device_changed(self, label: StreamLabel, device_name: str, recovered_ms: float) -> None:
        """Controller callback (event loop): announce recovery to the UI."""
        asyncio.get_running_loop().create_task(
            self._hub.broadcast_event(
                EVENT_CAPTURE_DEVICE_CHANGED,
                build_capture_device_changed_payload(device_name, recovered_ms),
            )
        )
