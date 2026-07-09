"""Per-stream pipeline: audio frames -> VAD gate -> windows -> merged words.

Purpose: runs one labelled stream ("me" or "them") through the full
transcription chain — slices frames into 512-sample VAD chunks, gates them
through the state machine, assembles confirmed speech into overlapping
windows, transcribes each window on a worker task, merges words, and
emits partial/final word lists upward.

Timing model: everything is meeting-relative seconds, derived from each
frame's monotonic timestamp minus the session anchor. A jump between a
frame's timestamp and the expected continuation (> 0.2 s — a device
change gap) CLOSES any open segment at the last heard time and realigns:
gaps are honest discontinuities, never stretched audio.

Pipeline position: one instance per stream inside
``engine.stt.live_capture_service``.

Security / fidelity invariants:
- Audio chunks flow through VAD/assembler and are DISCARDED once their
  windows are transcribed (audio-discarded-after-transcription).
- Words pass through verbatim; only window t_start offsets are added to
  timestamps (fidelity mandate — text is never touched).
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.stt.silero_onnx_voice_activity_detector import VAD_CHUNK_SAMPLES
from engine.stt.streaming_chunk_merger import StreamingChunkMerger
from engine.stt.streaming_window_assembler import AssembledWindow, StreamingWindowAssembler
from engine.stt.vad_gating_state_machine import VadGateEvent, VadGatingStateMachine
from engine.stt.word_token_types import TranscribedWindow, WordToken

logger = logging.getLogger(__name__)

# A frame arriving further than this from the expected continuation is a
# discontinuity (device change / driver stall) — close the open segment.
_GAP_TOLERANCE_S = 0.2

# Lookback depth: must cover min_speech (0.25 s = 8 chunks) so a segment's
# retroactive open time is always inside the buffer; 32 chunks ≈ 1 s.
_LOOKBACK_CHUNKS = 32

_CHUNK_SECONDS = VAD_CHUNK_SAMPLES / PIPELINE_SAMPLE_RATE

# Async callbacks up to the session layer.
PartialCallback = Callable[[list[WordToken]], Awaitable[None]]
FinalCallback = Callable[
    [list[WordToken], float, float, npt.NDArray[np.float32]], Awaitable[None]
]  # words, t_open, t_close, segment_audio
TranscribeFn = Callable[[npt.NDArray[np.float32]], Awaitable[list[WordToken]]]
VadProbabilityFn = Callable[[npt.NDArray[np.float32]], float]


@dataclass(frozen=True)
class _FinalizeSignal:
    """Sentinel telling a segment worker to flush and emit the final."""

    t_open: float
    t_close: float


class PerStreamTranscriptionPipeline:
    """Feed ``AudioFrame``s in arrival order; events come back via callbacks."""

    def __init__(
        self,
        stream: StreamLabel,
        anchor_monotonic: float,
        vad_probability: VadProbabilityFn,
        transcribe: TranscribeFn,
        on_partial: PartialCallback,
        on_final: FinalCallback,
        gate: VadGatingStateMachine | None = None,
    ) -> None:
        self.stream = stream
        self._anchor = anchor_monotonic
        self._vad_probability = vad_probability
        self._transcribe = transcribe
        self._on_partial = on_partial
        self._on_final = on_final
        self._gate = gate or VadGatingStateMachine()
        self._assembler = StreamingWindowAssembler()
        self._lookback: deque[tuple[float, npt.NDArray[np.float32]]] = deque(
            maxlen=_LOOKBACK_CHUNKS
        )
        self._residual = np.zeros(0, dtype=np.float32)
        self._residual_t0 = 0.0  # Meeting-relative time of _residual[0].
        self._last_chunk_end = 0.0
        self._segment_queue: asyncio.Queue[AssembledWindow | _FinalizeSignal] | None = None
        self._segment_t_open = 0.0
        self._worker_tasks: set[asyncio.Task[None]] = set()
        self._active_speaker_id: str | None = None

    @property
    def active_speaker_id(self) -> str | None:
        """Speaker id for the open segment on this stream (loopback diarization)."""
        return self._active_speaker_id

    def set_active_speaker_id(self, speaker_id: str) -> None:
        self._active_speaker_id = speaker_id

    async def feed(self, frame: AudioFrame) -> None:
        """Consume one frame: VAD-chunk it and advance the gate."""
        t_rel = frame.t_start_monotonic - self._anchor
        expected = self._residual_t0 + self._residual.size / PIPELINE_SAMPLE_RATE
        if self._residual.size and abs(t_rel - expected) > _GAP_TOLERANCE_S:
            # Device-change gap: end the world cleanly at the last heard
            # time, then realign to the new timeline (honest discontinuity).
            await self._close_open_segment(self._last_chunk_end)
            self._residual = np.zeros(0, dtype=np.float32)
        if self._residual.size == 0:
            self._residual_t0 = t_rel
        self._residual = np.concatenate([self._residual, frame.samples])

        while self._residual.size >= VAD_CHUNK_SAMPLES:
            chunk = self._residual[:VAD_CHUNK_SAMPLES]
            self._residual = self._residual[VAD_CHUNK_SAMPLES:]
            t0 = self._residual_t0
            self._residual_t0 = t0 + _CHUNK_SECONDS
            await self._process_chunk(chunk, t0, t0 + _CHUNK_SECONDS)

    async def finalize(self) -> None:
        """Capture stopping: close any open segment and await all workers."""
        await self._close_open_segment(self._last_chunk_end)
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=False)

    async def _process_chunk(
        self, chunk: npt.NDArray[np.float32], t0: float, t1: float
    ) -> None:
        self._last_chunk_end = t1
        self._lookback.append((t0, chunk))
        probability = self._vad_probability(chunk)
        opened_this_chunk = False
        for event, event_t in self._gate.process(probability, t0, t1):
            if event is VadGateEvent.SEGMENT_OPEN:
                self._open_segment(event_t)
                opened_this_chunk = True
            else:
                await self._enqueue_segment_close(event_t)
        if self._gate.is_in_speech and not opened_this_chunk:
            self._route_to_assembler(chunk)

    def _open_segment(self, t_open: float) -> None:
        """Start a segment; replay lookback audio from the retroactive start."""
        replay = [(t0, c) for t0, c in self._lookback if t0 + _CHUNK_SECONDS > t_open]
        # The assembler's clock starts at the first REPLAYED sample (may be
        # up to one chunk before t_open — the first syllable matters more
        # than 32 ms of lead-in).
        first_t0 = replay[0][0] if replay else t_open
        self._assembler.open(first_t0)
        self._segment_t_open = first_t0
        self._segment_queue = asyncio.Queue()
        self._active_speaker_id = None
        merger = StreamingChunkMerger()
        task = asyncio.create_task(self._segment_worker(self._segment_queue, merger))
        self._worker_tasks.add(task)
        task.add_done_callback(self._worker_tasks.discard)
        for _t0, chunk in replay:
            self._route_to_assembler(chunk)

    def _route_to_assembler(self, chunk: npt.NDArray[np.float32]) -> None:
        if self._segment_queue is None:
            return
        for window in self._assembler.feed(chunk):
            self._segment_queue.put_nowait(window)

    async def _enqueue_segment_close(self, t_close: float) -> None:
        """Close the assembler and hand the worker its finalize signal."""
        if self._segment_queue is None:
            return
        tail = self._assembler.close()
        if tail is not None:
            self._segment_queue.put_nowait(tail)
        self._segment_queue.put_nowait(_FinalizeSignal(self._segment_t_open, t_close))
        self._segment_queue = None  # Worker owns the rest of the segment.

    async def _close_open_segment(self, at_s: float) -> None:
        for event, event_t in self._gate.force_close(at_s):
            if event is VadGateEvent.SEGMENT_CLOSE:
                await self._enqueue_segment_close(event_t)

    async def _segment_worker(
        self,
        queue: asyncio.Queue[AssembledWindow | _FinalizeSignal],
        merger: StreamingChunkMerger,
    ) -> None:
        """Transcribe windows in order, merge, and emit partials + final."""
        segment_audio_parts: list[npt.NDArray[np.float32]] = []
        while True:
            item = await queue.get()
            if isinstance(item, _FinalizeSignal):
                words = merger.flush()
                if words:
                    segment_audio = (
                        np.concatenate(segment_audio_parts)
                        if segment_audio_parts
                        else np.zeros(0, dtype=np.float32)
                    )
                    await self._on_final(words, item.t_open, item.t_close, segment_audio)
                return
            segment_audio_parts.append(item.samples)
            try:
                window_words = await self._transcribe(item.samples)
            except Exception:
                # A failed window is a GAP, not a crash: the merger treats
                # the missing index as absent audio on flush (fail closed,
                # keep transcribing the rest of the segment).
                logger.exception(
                    "window %d transcription failed on stream %s", item.index, self.stream.value
                )
                continue
            shifted = tuple(
                # Verbatim text; timestamps shifted from window-relative to
                # meeting-relative (fidelity: text untouched).
                WordToken(w.text, w.t_start + item.t_start, w.t_end + item.t_start)
                for w in window_words
            )
            merger.add_window(
                TranscribedWindow(
                    index=item.index, t_start=item.t_start, t_end=item.t_end, words=shifted
                )
            )
            snapshot = merger.merged_words()
            if snapshot:
                await self._on_partial(snapshot)
