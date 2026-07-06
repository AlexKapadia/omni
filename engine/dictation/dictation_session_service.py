"""Mic-only dictation STT session: hold-to-talk capture -> verbatim text.

Purpose: owns one push-to-talk session at a time — opens the default
MICROPHONE only (never loopback; dictation is the user speaking), pumps
frames through its OWN VAD + Parakeet pipeline instances (composes
``engine.stt`` building blocks, modifies none of them), streams partial
text upward, and on release returns the verbatim transcript for
``dictation_finalization``.
Pipeline position: driven by the (deferred) server wiring for the
``dictation.begin`` / ``dictation.end`` commands; sits beside — never
inside — ``engine.stt.live_capture_service`` (meetings and dictation are
independent sessions with independent model instances).

Design note: no device-change watchdog — a hold-to-talk session lasts
seconds; if the mic dies mid-hold, frames simply stop and ``end()``
returns whatever was honestly heard (never fabricated audio).

Security / fidelity invariants:
- Audio frames are drained, transcribed, and dropped — never persisted
  (audio-discarded-after-transcription invariant).
- Emitted text is the models' verbatim output; words are joined with
  single spaces and NEVER rewritten (fidelity mandate).
- Fail closed on setup: missing models or an unopenable mic abort the
  session loudly; a silently-dead dictation would eat the user's words.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureBackend, CaptureStreamHandle
from engine.audio.resample_to_16k_mono import StreamingResamplerTo16kMono
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer
from engine.stt.model_weights_downloader import (
    PARAKEET_FILENAME,
    SILERO_VAD_FILENAME,
    models_directory,
)
from engine.stt.parakeet_nemo_transcriber import (
    ParakeetNemoTranscriber,
    stt_dependencies_available,
)
from engine.stt.per_stream_transcription_pipeline import PerStreamTranscriptionPipeline
from engine.stt.silero_onnx_voice_activity_detector import SileroOnnxVoiceActivityDetector
from engine.stt.word_token_types import WordToken

logger = logging.getLogger(__name__)

_DRAIN_INTERVAL_S = 0.05  # Same pump cadence as the live capture service.

# Typed seams (tests inject fakes; production uses the real classes).
VadFactory = Callable[[], Callable[[npt.NDArray[np.float32]], float]]
PartialTextCallback = Callable[[str], Awaitable[None]]


class DictationSessionError(Exception):
    """User-visible dictation failures (already running, mic missing...)."""


def _default_backend_factory() -> CaptureBackend:
    from engine.audio.pyaudiowpatch_capture_backend import PyAudioWpatchCaptureBackend

    return PyAudioWpatchCaptureBackend()


def words_to_verbatim_text(words: list[WordToken]) -> str:
    """Join word tokens with single spaces — the ONLY assembly step.

    Tokens pass through exactly as the model emitted them (fidelity
    mandate); stripping guards against tokenizers that emit edge spaces,
    never against the words themselves.
    """
    return " ".join(word.text.strip() for word in words if word.text.strip())


class DictationSessionService:
    """One per engine process. At most one dictation session at a time."""

    def __init__(
        self,
        *,
        backend_factory: Callable[[], CaptureBackend] = _default_backend_factory,
        models_dir: Path | None = None,
        transcriber: ParakeetNemoTranscriber | None = None,
        vad_factory: VadFactory | None = None,
        on_partial_text: PartialTextCallback | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self._models_dir = models_dir if models_dir is not None else models_directory()
        self._transcriber = transcriber
        self._vad_factory = vad_factory
        self._on_partial_text = on_partial_text
        self._models_ready = False
        self._load_lock = asyncio.Lock()
        # Per-session state (None/empty while idle).
        self._handle: CaptureStreamHandle | None = None
        self._pipeline: PerStreamTranscriptionPipeline | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._ring_buffer: TimestampedAudioRingBuffer | None = None
        # Final segments accumulate as (t_open, words) so ordering is by time.
        self._final_segments: list[tuple[float, list[WordToken]]] = []
        self._latest_partial: list[WordToken] = []

    @property
    def is_active(self) -> bool:
        return self._handle is not None

    async def begin(self) -> None:
        """Key down: open the default mic and start transcribing.

        Raises :class:`DictationSessionError` when already running, when
        models are missing, or when the mic cannot open (fail closed).
        """
        if self._handle is not None:
            raise DictationSessionError("dictation is already running")
        await self._ensure_models_loaded()
        anchor = time.monotonic()
        self._final_segments = []
        self._latest_partial = []
        self._pipeline = self._build_pipeline(anchor)
        ring_buffer = TimestampedAudioRingBuffer()
        self._ring_buffer = ring_buffer
        backend = self._backend_factory()
        try:
            # Mic ONLY — dictation never touches loopback (least capture).
            self._handle = await asyncio.to_thread(
                self._open_microphone_stream, backend, ring_buffer
            )
        except Exception as exc:
            self._pipeline = None
            self._ring_buffer = None
            raise DictationSessionError(f"could not open microphone: {exc}") from exc
        self._drain_task = asyncio.create_task(self._drain_loop(ring_buffer))
        logger.info("dictation session started")

    async def end(self) -> str:
        """Key up: stop capture, flush the pipeline, return verbatim text."""
        handle = self._handle
        pipeline = self._pipeline
        if handle is None or pipeline is None:
            raise DictationSessionError("dictation is not running")
        await asyncio.to_thread(handle.close)  # No new audio past this point.
        if self._drain_task is not None:
            self._drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drain_task
        # One last synchronous drain: frames the pump had not reached yet
        # (the tail of the utterance) must still be transcribed.
        if self._ring_buffer is not None:
            for frame in self._ring_buffer.drain():
                await pipeline.feed(frame)
        await pipeline.finalize()  # Force-closes the gate; emits finals.
        text = self._assemble_verbatim_text()
        self._handle = None
        self._pipeline = None
        self._drain_task = None
        self._ring_buffer = None
        logger.info("dictation session ended (%d chars)", len(text))
        return text

    async def cancel(self) -> None:
        """Abort without a transcript (e.g. pill dismissed). Idempotent."""
        if self._handle is None:
            return
        with contextlib.suppress(DictationSessionError):
            await self.end()  # Reuse the teardown; the text is discarded.

    async def _ensure_models_loaded(self) -> None:
        """Own VAD + Parakeet instances; never shared with the meeting STT."""
        async with self._load_lock:
            if self._models_ready:
                return
            if self._vad_factory is None:
                vad_model = self._models_dir / SILERO_VAD_FILENAME
                if not vad_model.is_file():
                    raise DictationSessionError(f"VAD model missing: {vad_model}")
                self._vad_factory = lambda: SileroOnnxVoiceActivityDetector(vad_model)
            if self._transcriber is None:
                if not stt_dependencies_available():
                    raise DictationSessionError(
                        "STT dependencies not installed (uv sync --extra stt)"
                    )
                self._transcriber = ParakeetNemoTranscriber(
                    self._models_dir / PARAKEET_FILENAME
                )
            if not self._transcriber.is_loaded:
                # Heavy load off the event loop (heartbeats keep flowing).
                await asyncio.to_thread(self._transcriber.load)
            self._models_ready = True

    def _open_microphone_stream(
        self, backend: CaptureBackend, ring_buffer: TimestampedAudioRingBuffer
    ) -> CaptureStreamHandle:
        """Probe + open the CURRENT default microphone (blocking; threaded)."""
        spec = backend.probe_default_device(StreamLabel.ME)
        resampler = StreamingResamplerTo16kMono(spec.sample_rate, spec.channels)

        def on_chunk(raw: bytes, t_end_monotonic: float) -> None:
            # Audio callback thread: resample + buffer only, never block.
            try:
                samples = resampler.process(raw)
            except ValueError:
                logger.exception("dropping malformed dictation audio chunk")
                return
            if samples.size == 0:
                return
            t_start = t_end_monotonic - samples.size / PIPELINE_SAMPLE_RATE
            ring_buffer.append(
                AudioFrame(stream=StreamLabel.ME, samples=samples, t_start_monotonic=t_start)
            )

        handle = backend.open_capture_stream(spec, on_chunk)
        logger.info("dictation mic open on %r (%d Hz)", spec.name, spec.sample_rate)
        return handle

    def _build_pipeline(self, anchor: float) -> PerStreamTranscriptionPipeline:
        assert self._vad_factory is not None and self._transcriber is not None  # noqa: S101
        transcriber = self._transcriber

        async def transcribe(samples: npt.NDArray[np.float32]) -> list[WordToken]:
            return await asyncio.to_thread(transcriber.transcribe_window, samples)

        async def on_partial(words: list[WordToken]) -> None:
            self._latest_partial = words
            if self._on_partial_text is not None:
                # Live partial for the pill: finals-so-far + current segment.
                await self._on_partial_text(self._partial_snapshot_text(words))

        async def on_final(words: list[WordToken], t_open: float, t_close: float) -> None:
            self._final_segments.append((t_open, words))
            self._latest_partial = []

        return PerStreamTranscriptionPipeline(
            stream=StreamLabel.ME,
            anchor_monotonic=anchor,
            vad_probability=self._vad_factory(),  # Fresh stateful VAD per session.
            transcribe=transcribe,
            on_partial=on_partial,
            on_final=on_final,
        )

    def _partial_snapshot_text(self, current_words: list[WordToken]) -> str:
        finals = [w for _t, words in sorted(self._final_segments) for w in words]
        return words_to_verbatim_text([*finals, *current_words])

    def _assemble_verbatim_text(self) -> str:
        """Finalised segments in time order, joined — nothing else."""
        ordered = [w for _t, words in sorted(self._final_segments) for w in words]
        return words_to_verbatim_text(ordered)

    async def _drain_loop(self, ring_buffer: TimestampedAudioRingBuffer) -> None:
        """Pump frames into the pipeline; frames are dropped after use
        (audio-discarded-after-transcription invariant)."""
        pipeline = self._pipeline
        while pipeline is not None:
            for frame in ring_buffer.drain():
                await pipeline.feed(frame)
            await asyncio.sleep(_DRAIN_INTERVAL_S)
