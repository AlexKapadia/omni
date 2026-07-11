"""Real microphone capture for the Naomi loop: default mic → 16k frames.

Purpose: opens the CURRENT default microphone (never loopback — Naomi listens
to the user), resamples to 16kHz mono, and pumps ``AudioFrame``s to the
orchestrator's async ``feed`` seam. The audio-callback thread only resamples
and buffers; a drain task bridges those frames onto the event loop (the same
sync-callback → ring-buffer → async-drain pattern the dictation session uses,
kept independent so Naomi and dictation never share a capture).
Pipeline position: the ``start_capture`` seam injected into
``engine.naomi.naomi_turn_orchestrator`` by the loop gateway; the live test
and unit tests bypass it and push frames straight to ``feed_audio_frame``.

Security / fidelity invariants: frames are drained and dropped after the
pipeline transcribes them (audio-discarded-after-transcription); nothing here
persists audio, and only the default mic is opened (least capture).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureBackend, CaptureStreamHandle
from engine.audio.resample_to_16k_mono import StreamingResamplerTo16kMono
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer

logger = logging.getLogger(__name__)

_DRAIN_INTERVAL_S = 0.05  # Same pump cadence as the live/dictation capture.

FrameSink = Callable[[AudioFrame], Awaitable[None]]
StopCapture = Callable[[], Awaitable[None]]


def _default_backend_factory() -> CaptureBackend:
    from engine.audio.pyaudiowpatch_capture_backend import PyAudioWpatchCaptureBackend

    return PyAudioWpatchCaptureBackend()


def _open_microphone_stream(
    backend: CaptureBackend,
    ring_buffer: TimestampedAudioRingBuffer,
    *,
    preferred_me_device_key: str | None = None,
) -> CaptureStreamHandle:
    """Open preferred mic when set; otherwise the current default (threaded)."""
    if preferred_me_device_key:
        spec = backend.resolve_input_device(preferred_me_device_key)
    else:
        spec = backend.probe_default_device(StreamLabel.ME)
    resampler = StreamingResamplerTo16kMono(spec.sample_rate, spec.channels)

    def on_chunk(raw: bytes, t_end_monotonic: float) -> None:
        # Audio callback thread: resample + buffer only, never block.
        try:
            samples = resampler.process(raw)
        except ValueError:
            logger.exception("dropping malformed Naomi mic chunk")
            return
        if samples.size == 0:
            return
        t_start = t_end_monotonic - samples.size / PIPELINE_SAMPLE_RATE
        ring_buffer.append(
            AudioFrame(stream=StreamLabel.ME, samples=samples, t_start_monotonic=t_start)
        )

    handle = backend.open_capture_stream(spec, on_chunk)
    logger.info("Naomi mic open on %r (%d Hz)", spec.name, spec.sample_rate)
    return handle


async def start_naomi_mic_capture(
    sink: FrameSink,
    *,
    backend_factory: Callable[[], CaptureBackend] = _default_backend_factory,
    preferred_me_device_key: str | None = None,
) -> StopCapture:
    """Open the mic and stream frames to ``sink``; returns an idempotent stop.

    Raises the backend's error if the mic cannot open (fail closed — a
    silently-dead mic would eat the user's words).
    """
    backend = backend_factory()
    ring_buffer = TimestampedAudioRingBuffer()
    mic_key = preferred_me_device_key.strip() if preferred_me_device_key else None
    handle = await asyncio.to_thread(
        _open_microphone_stream,
        backend,
        ring_buffer,
        preferred_me_device_key=mic_key,
    )

    async def drain() -> None:
        while True:
            for frame in ring_buffer.drain():
                await sink(frame)
            await asyncio.sleep(_DRAIN_INTERVAL_S)

    drain_task = asyncio.create_task(drain())

    async def stop() -> None:
        await asyncio.to_thread(handle.close)  # no new audio past this point
        drain_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drain_task
        # Flush the tail the pump had not reached (the end of the utterance).
        for frame in ring_buffer.drain():
            await sink(frame)

    return stop
