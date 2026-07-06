"""Ring buffer: FIFO order, duration bound with drop-oldest, thread safety.

The buffer is the audio hand-off between driver callback threads and the
asyncio pipeline: ordering, bounded memory, and honest drop accounting
are its whole contract.
"""

import threading

import numpy as np
import pytest

from engine.audio.audio_frame_types import AudioFrame, StreamLabel
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer


def _frame(t: float, seconds: float = 0.1, label: StreamLabel = StreamLabel.ME) -> AudioFrame:
    return AudioFrame(
        stream=label,
        samples=np.zeros(int(seconds * 16_000), dtype=np.float32),
        t_start_monotonic=t,
    )


def test_drain_returns_frames_in_fifo_order_and_empties_the_buffer() -> None:
    buffer = TimestampedAudioRingBuffer(max_buffered_seconds=10.0)
    for i in range(5):
        buffer.append(_frame(float(i)))
    drained = buffer.drain()
    assert [f.t_start_monotonic for f in drained] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert buffer.drain() == []  # Emptied.
    assert buffer.buffered_seconds == 0.0


def test_exceeding_the_duration_cap_drops_the_oldest_frames() -> None:
    buffer = TimestampedAudioRingBuffer(max_buffered_seconds=0.5)
    for i in range(10):  # 1.0 s total of 0.1 s frames into a 0.5 s cap.
        buffer.append(_frame(float(i)))
    drained = buffer.drain()
    # The NEWEST frames survive (live transcript wants fresh audio).
    assert [f.t_start_monotonic for f in drained] == [5.0, 6.0, 7.0, 8.0, 9.0]
    assert buffer.dropped_seconds_total == pytest.approx(0.5)


def test_exactly_at_the_cap_drops_nothing_boundary_exact() -> None:
    buffer = TimestampedAudioRingBuffer(max_buffered_seconds=0.5)
    for i in range(5):  # Exactly 0.5 s buffered: within the cap.
        buffer.append(_frame(float(i)))
    assert buffer.dropped_seconds_total == 0.0
    assert len(buffer.drain()) == 5


def test_one_oversized_frame_is_kept_never_an_empty_buffer() -> None:
    """A single frame larger than the cap must still be deliverable."""
    buffer = TimestampedAudioRingBuffer(max_buffered_seconds=0.5)
    buffer.append(_frame(0.0, seconds=2.0))
    drained = buffer.drain()
    assert len(drained) == 1 and drained[0].duration_s == pytest.approx(2.0)


def test_mixed_stream_labels_ride_the_same_buffer_untouched() -> None:
    buffer = TimestampedAudioRingBuffer()
    buffer.append(_frame(0.0, label=StreamLabel.THEM))
    buffer.append(_frame(0.1, label=StreamLabel.ME))
    labels = [f.stream for f in buffer.drain()]
    assert labels == [StreamLabel.THEM, StreamLabel.ME]


def test_invalid_cap_fails_closed() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        TimestampedAudioRingBuffer(max_buffered_seconds=0.0)


def test_concurrent_producers_and_consumer_lose_nothing_under_the_cap() -> None:
    """Two producer threads + a draining consumer: every frame appended is
    either drained or (here, cap is generous) never dropped — no
    corruption, no double-delivery."""
    buffer = TimestampedAudioRingBuffer(max_buffered_seconds=1_000.0)
    per_thread = 500
    received: list[AudioFrame] = []
    stop = threading.Event()

    def produce(offset: float) -> None:
        for i in range(per_thread):
            buffer.append(_frame(offset + i, seconds=0.01))

    def consume() -> None:
        while not stop.is_set():
            received.extend(buffer.drain())
        received.extend(buffer.drain())  # Final sweep.

    consumer = threading.Thread(target=consume)
    producers = [threading.Thread(target=produce, args=(base,)) for base in (0.0, 10_000.0)]
    consumer.start()
    for producer in producers:
        producer.start()
    for producer in producers:
        producer.join()
    stop.set()
    consumer.join()

    assert len(received) == 2 * per_thread
    stamps = [f.t_start_monotonic for f in received]
    assert len(set(stamps)) == len(stamps)  # No frame delivered twice.
    # Per-producer order is preserved through the FIFO.
    first = [s for s in stamps if s < 10_000.0]
    second = [s for s in stamps if s >= 10_000.0]
    assert first == sorted(first) and second == sorted(second)
