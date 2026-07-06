"""Streaming resampler: any device format -> 16 kHz mono float32.

Purpose: normalises raw capture chunks (any sample rate — 44.1 k / 48 k /
anything, any channel count, int16 PCM) into the single pipeline format
(``PIPELINE_SAMPLE_RATE`` mono float32) using soxr's streaming API so
filter state carries across chunk boundaries — chunked output is
sample-identical to one-shot output, no boundary artefacts.
Pipeline position: sits inside the capture path, between the PortAudio
callback and the ring buffer; one instance per open device stream.

Security invariant: pure in-memory transformation — audio is never
persisted here (local-only invariant).
"""

import numpy as np
import numpy.typing as npt
import soxr

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE

# int16 full-scale divisor for PCM -> float32 [-1, 1] conversion.
_INT16_FULL_SCALE = 32768.0


class StreamingResamplerTo16kMono:
    """Converts a stream of interleaved int16 PCM chunks to 16 kHz mono float32.

    One instance per capture stream: soxr's ``ResampleStream`` is stateful
    (polyphase filter memory), so reusing an instance across chunks is what
    guarantees boundary-exact output. Create a FRESH instance whenever a
    device (re)opens — stale filter state from a previous device would
    bleed into the new stream.
    """

    def __init__(self, input_sample_rate: int, input_channels: int) -> None:
        if input_sample_rate <= 0:
            raise ValueError(f"input_sample_rate must be positive, got {input_sample_rate}")
        if input_channels <= 0:
            raise ValueError(f"input_channels must be positive, got {input_channels}")
        self._input_sample_rate = input_sample_rate
        self._input_channels = input_channels
        # WHY no-op detection: soxr at ratio 1.0 still applies filter delay;
        # bypassing it keeps 16 kHz devices latency- and sample-exact.
        self._passthrough = input_sample_rate == PIPELINE_SAMPLE_RATE
        self._stream = (
            None
            if self._passthrough
            else soxr.ResampleStream(
                input_sample_rate,
                PIPELINE_SAMPLE_RATE,
                num_channels=1,  # Downmix happens before resampling (cheaper).
                dtype="float32",
                quality="HQ",
            )
        )

    def process(self, raw_interleaved_int16: bytes) -> npt.NDArray[np.float32]:
        """Convert one raw PCM chunk. Returns 16 kHz mono float32 samples.

        May return fewer/more samples than a naive ratio predicts for any
        single chunk (resampler buffering); over the whole stream the counts
        converge to ``len * 16000 / input_rate``.
        """
        interleaved = np.frombuffer(raw_interleaved_int16, dtype=np.int16)
        if interleaved.size == 0:
            return np.zeros(0, dtype=np.float32)
        if interleaved.size % self._input_channels != 0:
            # A torn chunk means the byte stream is corrupt — fail closed
            # loudly rather than silently desynchronising channels.
            raise ValueError(
                f"chunk of {interleaved.size} samples is not divisible by "
                f"{self._input_channels} channels"
            )
        as_float = interleaved.astype(np.float32) / _INT16_FULL_SCALE
        # Stereo/multichannel -> mono by channel mean: preserves loudness
        # balance and is what both VAD and STT models expect.
        frames = as_float.reshape(-1, self._input_channels)
        mono: npt.NDArray[np.float32] = frames.mean(axis=1, dtype=np.float32)
        if self._passthrough or self._stream is None:
            return mono
        resampled: npt.NDArray[np.float32] = self._stream.resample_chunk(mono, last=False)
        return resampled.astype(np.float32, copy=False)

    def flush(self) -> npt.NDArray[np.float32]:
        """Drain the resampler's tail (filter delay) when a stream closes.

        Called on device close/change so the final milliseconds of audio
        are not silently swallowed by the polyphase filter's lookahead.
        """
        if self._passthrough or self._stream is None:
            return np.zeros(0, dtype=np.float32)
        tail: npt.NDArray[np.float32] = self._stream.resample_chunk(
            np.zeros(0, dtype=np.float32), last=True
        )
        return tail.astype(np.float32, copy=False)
