"""Per-stream pipeline end-to-end (mocked VAD + transcriber, no models).

Feeds synthetic frames through the REAL chunking/gating/windowing/merging
chain with an amplitude-scripted VAD and a deterministic fake transcriber:
segments must open/close correctly, windows must reach the transcriber at
the exact 4 s / 3.2 s-hop geometry, finals must carry merged verbatim
words, device gaps must close segments honestly, and a failed window must
degrade to a gap — never a crash.
"""

import numpy as np
import numpy.typing as npt
import pytest

from engine.audio.audio_frame_types import AudioFrame, StreamLabel
from engine.stt.per_stream_transcription_pipeline import PerStreamTranscriptionPipeline
from engine.stt.word_token_types import WordToken

ANCHOR = 1000.0  # Arbitrary monotonic anchor: pipeline math must not care.
FRAME_N = 1600  # 0.1 s frames, like real capture output.


def amplitude_vad(chunk: npt.NDArray[np.float32]) -> float:
    """Deterministic VAD stand-in: loud chunk = speech."""
    return 0.99 if float(np.abs(chunk).mean()) > 0.01 else 0.01


class FakeTranscriber:
    """Returns one word per window, stamped near the window's END so it
    falls outside the next overlap cut (deterministic merge behaviour)."""

    def __init__(self) -> None:
        self.received_sizes: list[int] = []
        self.calls = 0
        self.fail_on_calls: set[int] = set()

    async def __call__(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        self.calls += 1
        if self.calls in self.fail_on_calls:
            raise RuntimeError("synthetic transcription failure")
        self.received_sizes.append(samples.size)
        duration = samples.size / 16_000
        return [WordToken(f"w{self.calls}", max(0.0, duration - 1.0), max(0.1, duration - 0.8))]


class EventCollector:
    def __init__(self) -> None:
        self.partials: list[list[WordToken]] = []
        self.finals: list[tuple[list[WordToken], float, float]] = []

    async def on_partial(self, words: list[WordToken]) -> None:
        self.partials.append(list(words))

    async def on_final(
        self,
        words: list[WordToken],
        t_open: float,
        t_close: float,
        _segment_audio: npt.NDArray[np.float32] | None = None,
    ) -> None:
        self.finals.append((list(words), t_open, t_close))


def make_pipeline(
    collector: EventCollector, transcriber: FakeTranscriber
) -> PerStreamTranscriptionPipeline:
    return PerStreamTranscriptionPipeline(
        stream=StreamLabel.THEM,
        anchor_monotonic=ANCHOR,
        vad_probability=amplitude_vad,
        transcribe=transcriber,
        on_partial=collector.on_partial,
        on_final=collector.on_final,
    )


def frames(script: list[tuple[float, float]]) -> list[AudioFrame]:
    """Build 0.1 s frames from (seconds, amplitude) runs, contiguous in time."""
    result, t = [], 0.0
    for seconds, amplitude in script:
        for _ in range(round(seconds / 0.1)):
            result.append(
                AudioFrame(
                    stream=StreamLabel.THEM,
                    samples=np.full(FRAME_N, amplitude, dtype=np.float32),
                    t_start_monotonic=ANCHOR + t,
                )
            )
            t += 0.1
    return result


async def test_speech_burst_produces_windows_partials_and_a_merged_final() -> None:
    collector, transcriber = EventCollector(), FakeTranscriber()
    pipeline = make_pipeline(collector, transcriber)
    # 0.5 s silence, 5 s speech, 1 s silence: one segment, two windows.
    for frame in frames([(0.5, 0.0), (5.0, 0.5), (1.0, 0.0)]):
        await pipeline.feed(frame)
    await pipeline.finalize()

    # Window geometry: full 4 s window (64000 samples) + a real tail.
    assert transcriber.received_sizes[0] == 64_000
    assert len(transcriber.received_sizes) == 2
    assert transcriber.received_sizes[1] > 800

    assert len(collector.finals) == 1
    words, t_open, t_close = collector.finals[0]
    # Speech started at 0.5 s: retroactive open lands on the covering VAD
    # chunk boundary (0.48), close at silence start (~5.5).
    assert t_open == pytest.approx(0.48, abs=0.05)
    assert t_close == pytest.approx(5.5, abs=0.05)
    assert [w.text for w in words] == ["w1", "w2"]  # Merged, verbatim, in order.
    assert words[0].t_start == pytest.approx(0.48 + 3.0, abs=0.05)  # Shifted to stream time.
    assert len(collector.partials) >= 2  # One live update per transcribed window.
    assert [w.text for w in collector.partials[0]] == ["w1"]


async def test_silence_only_never_calls_the_transcriber() -> None:
    collector, transcriber = EventCollector(), FakeTranscriber()
    pipeline = make_pipeline(collector, transcriber)
    for frame in frames([(3.0, 0.0)]):
        await pipeline.feed(frame)
    await pipeline.finalize()
    assert transcriber.calls == 0
    assert collector.finals == [] and collector.partials == []


async def test_short_utterance_under_one_window_still_finalises() -> None:
    collector, transcriber = EventCollector(), FakeTranscriber()
    pipeline = make_pipeline(collector, transcriber)
    for frame in frames([(0.5, 0.0), (1.0, 0.5), (1.0, 0.0)]):
        await pipeline.feed(frame)
    await pipeline.finalize()
    assert len(collector.finals) == 1  # Tail-only segment.
    assert transcriber.calls == 1


async def test_device_gap_closes_the_segment_and_a_new_one_follows() -> None:
    """Timestamp discontinuity = device change: the open segment must
    close at the last heard time, then transcription resumes cleanly."""
    collector, transcriber = EventCollector(), FakeTranscriber()
    pipeline = make_pipeline(collector, transcriber)
    for frame in frames([(2.0, 0.5)]):
        await pipeline.feed(frame)
    # The stream jumps 8 s forward (endpoint switch lost audio).
    t = 10.0
    for _ in range(20):  # 2 s of speech on the new device timeline.
        await pipeline.feed(
            AudioFrame(
                stream=StreamLabel.THEM,
                samples=np.full(FRAME_N, 0.5, dtype=np.float32),
                t_start_monotonic=ANCHOR + t,
            )
        )
        t += 0.1
    await pipeline.finalize()
    assert len(collector.finals) == 2
    first_words, _first_open, first_close = collector.finals[0]
    second_words, second_open, _second_close = collector.finals[1]
    assert first_close <= 2.1  # Closed at the last pre-gap audio, not stretched.
    assert second_open == pytest.approx(10.0, abs=0.05)  # New honest timeline.
    assert first_words and second_words


async def test_failed_window_transcription_becomes_a_gap_not_a_crash() -> None:
    collector, transcriber = EventCollector(), FakeTranscriber()
    transcriber.fail_on_calls = {1}  # First window dies (transient GPU error).
    pipeline = make_pipeline(collector, transcriber)
    for frame in frames([(0.5, 0.0), (8.0, 0.5), (1.0, 0.0)]):
        await pipeline.feed(frame)
    await pipeline.finalize()
    assert len(collector.finals) == 1
    words, _, _ = collector.finals[0]
    assert words, "surviving windows must still produce the final"
    assert "w1" not in [w.text for w in words]  # The failed window is a gap.


async def test_empty_model_output_emits_no_final() -> None:
    """VAD fired but the model heard nothing: no words -> no segment."""
    collector = EventCollector()

    async def silent_transcribe(samples: npt.NDArray[np.float32]) -> list[WordToken]:
        return []

    pipeline = PerStreamTranscriptionPipeline(
        stream=StreamLabel.ME,
        anchor_monotonic=ANCHOR,
        vad_probability=amplitude_vad,
        transcribe=silent_transcribe,
        on_partial=collector.on_partial,
        on_final=collector.on_final,
    )
    for frame in frames([(1.5, 0.5), (1.0, 0.0)]):
        await pipeline.feed(frame)
    await pipeline.finalize()
    assert collector.finals == [] and collector.partials == []


async def test_finalize_flushes_a_still_open_segment() -> None:
    """Capture stopped mid-sentence: the open segment must still finalise."""
    collector, transcriber = EventCollector(), FakeTranscriber()
    pipeline = make_pipeline(collector, transcriber)
    for frame in frames([(2.0, 0.5)]):  # Speech with no closing silence.
        await pipeline.feed(frame)
    await pipeline.finalize()
    assert len(collector.finals) == 1
