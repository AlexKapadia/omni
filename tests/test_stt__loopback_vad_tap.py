"""Loopback VAD tap: probabilities reach detection; failures never break STT.

Pins the additive M6 seam in ``engine.stt.loopback_vad_probability_tap``:
the wrapped VAD returns the inner probability unchanged (transcription
arithmetic untouched), forwards ``(monotonic_ts, probability)`` to the
late-bound tap, tolerates the tap being absent or attached later, and
swallows tap crashes (a detection bug must never break live capture).
"""

from collections.abc import Callable

import numpy as np

from engine.stt.loopback_vad_probability_tap import wrap_vad_with_loopback_tap

CHUNK = np.zeros(512, dtype=np.float32)


def test_wrapped_vad_returns_the_inner_probability_exactly() -> None:
    wrapped = wrap_vad_with_loopback_tap(lambda samples: 0.73, lambda: None)
    assert wrapped(CHUNK) == 0.73  # exact pass-through, no reweighting


def test_tap_receives_each_probability_with_a_monotonic_timestamp() -> None:
    received: list[tuple[float, float]] = []
    probabilities = iter([0.1, 0.9, 0.5])
    wrapped = wrap_vad_with_loopback_tap(
        lambda samples: next(probabilities), lambda: (lambda ts, p: received.append((ts, p)))
    )
    for _ in range(3):
        wrapped(CHUNK)
    assert [p for _ts, p in received] == [0.1, 0.9, 0.5]
    timestamps = [ts for ts, _p in received]
    assert timestamps == sorted(timestamps)  # monotonic clock, stream order


def test_tap_is_late_bound_attaching_mid_stream_starts_forwarding() -> None:
    received: list[tuple[float, float]] = []
    # The server assigns the tap after construction (late binding).
    tap_holder: list[Callable[[float, float], None] | None] = [None]
    wrapped = wrap_vad_with_loopback_tap(lambda samples: 0.4, lambda: tap_holder[0])
    wrapped(CHUNK)
    assert received == []  # nothing forwarded while unwired
    tap_holder[0] = lambda ts, p: received.append((ts, p))
    wrapped(CHUNK)
    assert len(received) == 1 and received[0][1] == 0.4


def test_a_crashing_tap_never_breaks_the_vad_result() -> None:
    def exploding_tap(ts: float, p: float) -> None:
        raise ValueError("samples must arrive in stream order")

    wrapped = wrap_vad_with_loopback_tap(lambda samples: 0.66, lambda: exploding_tap)
    # The gate still gets its probability; capture continues (fail closed
    # on detection, never on the user's own transcription).
    assert wrapped(CHUNK) == 0.66
    assert wrapped(CHUNK) == 0.66  # and keeps working on subsequent chunks
