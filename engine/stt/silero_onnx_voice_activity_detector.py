"""Silero VAD v5 (ONNX) wrapper: 512-sample chunks -> speech probability.

Purpose: runs the Silero voice-activity model via onnxruntime (CPU — the
model is ~2 MB and real-time on one core; the GPU is reserved for
Parakeet). One instance per audio stream because the model is STATEFUL:
its recurrent state AND its 64-sample context window must follow one
stream only, never interleave two.

Model I/O contract (pinned by the silero_vad.onnx v5 graph, mirroring the
official OnnxWrapper): each call feeds ``[context(64) + chunk(512)]`` =
576 samples at 16 kHz, plus the recurrent ``state`` (2, 1, 128); the
context is the LAST 64 samples of the previous chunk. Omitting the
context collapses probabilities (measured: max 0.15 on clear speech), so
it is not optional.

Pipeline position: inside ``engine.stt.per_stream_transcription_pipeline``,
directly ahead of ``engine.stt.vad_gating_state_machine``.

Security invariant: inference is fully local (onnxruntime, no network);
input audio is read, scored, and released — never stored (local-only /
discard-after-transcription invariants).
"""

from pathlib import Path

import numpy as np
import numpy.typing as npt

# Silero v5 operates on exactly 512 new samples at 16 kHz (32 ms) per call.
VAD_CHUNK_SAMPLES = 512
# Plus 64 samples of look-back context carried from the previous chunk.
_CONTEXT_SAMPLES = 64
_VAD_SAMPLE_RATE = 16_000
# Recurrent state shape pinned by the silero_vad.onnx v5 graph.
_STATE_SHAPE = (2, 1, 128)


class SileroOnnxVoiceActivityDetector:
    """Stateful per-stream speech-probability scorer."""

    def __init__(self, model_path: Path) -> None:
        # Lazy import keeps module import cheap for tooling; onnxruntime is
        # a hard runtime dependency (main manifest), so this always works.
        import onnxruntime

        if not model_path.is_file():
            # Fail closed: a missing model must abort STT setup loudly, not
            # degrade into "everything is silence".
            raise FileNotFoundError(f"Silero VAD model not found: {model_path}")
        self._session = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],  # WHY CPU: tiny model; GPU is Parakeet's.
        )
        self._state: npt.NDArray[np.float32] = np.zeros(_STATE_SHAPE, dtype=np.float32)
        self._context: npt.NDArray[np.float32] = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)
        self._sample_rate = np.array(_VAD_SAMPLE_RATE, dtype=np.int64)

    def __call__(self, chunk: npt.NDArray[np.float32]) -> float:
        """Score one 32 ms chunk. Returns P(speech) in [0, 1].

        Raises on a wrong-sized chunk (fail closed — a silent resize would
        skew every probability after it).
        """
        if chunk.shape != (VAD_CHUNK_SAMPLES,):
            raise ValueError(
                f"VAD chunk must be exactly {VAD_CHUNK_SAMPLES} samples, got {chunk.shape}"
            )
        # v5 contract: 64 samples of previous-chunk context prepended.
        model_input = np.concatenate([self._context, chunk]).astype(np.float32, copy=False)
        outputs = self._session.run(
            None,
            {
                "input": model_input.reshape(1, -1),
                "state": self._state,
                "sr": self._sample_rate,
            },
        )
        probability, self._state = float(outputs[0].item()), outputs[1]
        self._context = chunk[-_CONTEXT_SAMPLES:]
        return probability

    def reset(self) -> None:
        """Clear recurrent state + context (between unrelated audio streams)."""
        self._state = np.zeros(_STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)
