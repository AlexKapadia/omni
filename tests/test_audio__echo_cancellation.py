"""Echo cancellation processor tests."""

import numpy as np

from engine.audio.echo_cancellation_processor import apply_echo_cancellation


def test_apply_echo_cancellation_reduces_loopback() -> None:
    mic = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    loop = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    out = apply_echo_cancellation(mic, loop, strength=1.0)
    assert np.allclose(out, 0.0, atol=1e-6)
