"""Resampler correctness: rates, downmix, chunk-boundary exactness.

The resampler is the single normalisation point for all captured audio;
if it is wrong, everything downstream transcribes garbage. These tests
pin sample-count convergence for 44.1 k/48 k inputs, stereo->mono
downmix math, tone preservation through resampling, and — critically —
that CHUNKED streaming output equals ONE-SHOT output (soxr filter state
carries across boundaries).
"""

import numpy as np
import pytest

from engine.audio.resample_to_16k_mono import StreamingResamplerTo16kMono


def _sine_int16(
    frequency_hz: float, seconds: float, rate: int, amplitude: float = 0.5
) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * frequency_hz * t) * amplitude * 32767).astype(np.int16)


def _interleave_stereo(left: np.ndarray, right: np.ndarray) -> bytes:
    stereo = np.empty(left.size * 2, dtype=np.int16)
    stereo[0::2] = left
    stereo[1::2] = right
    return stereo.tobytes()


def _process_all(
    resampler: StreamingResamplerTo16kMono, raw: bytes, chunk_bytes: int
) -> np.ndarray:
    pieces = [
        resampler.process(raw[i : i + chunk_bytes]) for i in range(0, len(raw), chunk_bytes)
    ]
    pieces.append(resampler.flush())
    return np.concatenate(pieces)


@pytest.mark.parametrize("rate", [44_100, 48_000, 22_050, 96_000])
def test_output_sample_count_converges_to_the_exact_ratio(rate: int) -> None:
    """2 s of mono input at any rate -> 32000 +/- a filter-tail few samples."""
    resampler = StreamingResamplerTo16kMono(rate, 1)
    raw = _sine_int16(440.0, 2.0, rate).tobytes()
    out = _process_all(resampler, raw, chunk_bytes=4096)
    expected = int(2.0 * 16_000)
    assert abs(out.size - expected) <= 16, f"{out.size} vs {expected}"


def test_441k_stereo_to_16k_mono_boundary_sample_counts() -> None:
    """The classic 44.1k->16k non-integer ratio with stereo interleaving."""
    left = _sine_int16(300.0, 1.5, 44_100)
    right = _sine_int16(300.0, 1.5, 44_100)
    resampler = StreamingResamplerTo16kMono(44_100, 2)
    out = _process_all(resampler, _interleave_stereo(left, right), chunk_bytes=1764 * 4)
    assert abs(out.size - 24_000) <= 16


def test_stereo_downmix_is_the_channel_mean() -> None:
    """L = +0.5, R = -0.5 constant -> mono must be ~0 (mean, not sum/first)."""
    left = np.full(16_000, 16384, dtype=np.int16)
    right = np.full(16_000, -16384, dtype=np.int16)
    resampler = StreamingResamplerTo16kMono(16_000, 2)  # Passthrough rate isolates downmix.
    out = resampler.process(_interleave_stereo(left, right))
    assert out.size == 16_000
    assert np.abs(out).max() < 1e-4


def test_16k_mono_passthrough_is_sample_exact() -> None:
    """Same-rate input must come through bit-faithfully (no filter delay)."""
    samples = _sine_int16(500.0, 0.5, 16_000)
    resampler = StreamingResamplerTo16kMono(16_000, 1)
    out = resampler.process(samples.tobytes())
    assert out.size == samples.size
    np.testing.assert_allclose(out, samples.astype(np.float32) / 32768.0, atol=1e-7)


def test_tone_frequency_is_preserved_through_48k_resample() -> None:
    """A 1 kHz tone at 48 k must still be ~1 kHz at 16 k (zero-crossing count)."""
    resampler = StreamingResamplerTo16kMono(48_000, 1)
    raw = _sine_int16(1000.0, 2.0, 48_000).tobytes()
    out = _process_all(resampler, raw, chunk_bytes=9600)
    # Count positive-going zero crossings in the steady middle of the signal.
    middle = out[out.size // 4 : 3 * out.size // 4]
    crossings = int(np.sum((middle[:-1] < 0) & (middle[1:] >= 0)))
    seconds = middle.size / 16_000
    measured_hz = crossings / seconds
    assert abs(measured_hz - 1000.0) < 10.0, f"tone drifted to {measured_hz:.1f} Hz"


def test_chunked_output_equals_one_shot_output() -> None:
    """Boundary exactness: many tiny odd-sized chunks == one giant chunk.

    This is THE streaming property: soxr state must carry across calls so
    chunk boundaries leave no seams.
    """
    rng = np.random.default_rng(1234)
    noise = (rng.uniform(-0.8, 0.8, 48_000 * 2) * 32767).astype(np.int16)
    raw = noise.tobytes()

    one_shot = StreamingResamplerTo16kMono(48_000, 1)
    reference = np.concatenate([one_shot.process(raw), one_shot.flush()])

    chunked = StreamingResamplerTo16kMono(48_000, 1)
    pieces, position = [], 0
    chunk_sizes = rng.integers(2, 4001, size=1000)  # Odd, varied chunk sizes.
    for size in chunk_sizes:
        if position >= len(raw):
            break
        take = int(size) * 2  # int16 -> bytes, keep sample-aligned.
        pieces.append(chunked.process(raw[position : position + take]))
        position += take
    pieces.append(chunked.process(raw[position:]))
    pieces.append(chunked.flush())
    result = np.concatenate(pieces)

    assert result.size == reference.size
    np.testing.assert_allclose(result, reference, atol=1e-6)


def test_empty_chunk_yields_empty_output() -> None:
    resampler = StreamingResamplerTo16kMono(48_000, 2)
    assert resampler.process(b"").size == 0


def test_torn_chunk_not_divisible_by_channels_fails_closed() -> None:
    """3 int16 samples into a stereo stream = corrupt byte stream -> raise."""
    resampler = StreamingResamplerTo16kMono(48_000, 2)
    with pytest.raises(ValueError, match="not divisible"):
        resampler.process(np.zeros(3, dtype=np.int16).tobytes())


@pytest.mark.parametrize(("rate", "channels"), [(0, 1), (-8000, 1), (16_000, 0), (16_000, -2)])
def test_invalid_construction_parameters_fail_closed(rate: int, channels: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        StreamingResamplerTo16kMono(rate, channels)


def test_five_channel_input_downmixes_without_desync() -> None:
    """Exotic channel counts (5.1-ish loopback) must still average cleanly."""
    frames = 4800
    interleaved = np.zeros(frames * 5, dtype=np.int16)
    for channel in range(5):
        interleaved[channel::5] = 10_000  # All channels equal -> mean equals each.
    resampler = StreamingResamplerTo16kMono(48_000, 5)
    out = np.concatenate(
        [resampler.process(interleaved.tobytes()), resampler.flush()]
    )
    assert abs(out.size - 1600) <= 16
    # Steady-state value ~ 10000/32768; check the middle away from filter edges.
    middle = out[out.size // 3 : 2 * out.size // 3]
    np.testing.assert_allclose(middle, 10_000 / 32768.0, atol=5e-3)
