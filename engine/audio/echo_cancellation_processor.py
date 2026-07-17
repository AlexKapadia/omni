"""Optional acoustic echo cancellation — attenuates loopback bleed into mic."""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt


def apply_echo_cancellation(
    mic_samples: np.ndarray,
    loopback_samples: np.ndarray,
    *,
    strength: float = 0.35,
) -> np.ndarray:
    """Subtract a scaled loopback signal from the mic stream (simple AEC).

  When shapes differ, the shorter stream is zero-padded. This is a lightweight
  processor — not full WebRTC AEC — but reduces echo during shared speakers.
    """
    if mic_samples.size == 0:
        return mic_samples
    length = max(mic_samples.shape[0], loopback_samples.shape[0])
    mic = np.pad(mic_samples.astype(np.float32), (0, length - mic_samples.shape[0]))
    loop = np.pad(loopback_samples.astype(np.float32), (0, length - loopback_samples.shape[0]))
    out = mic - np.clip(strength, 0.0, 1.0) * loop
    return cast(npt.NDArray[np.floating], np.clip(out, -1.0, 1.0))
