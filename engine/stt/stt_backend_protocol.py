"""Protocol for pluggable speech-to-text backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class SttSegment:
    text: str
    t_start: float
    t_end: float
    stream: str = "them"


class SttBackend(Protocol):
    """Minimal STT surface used by dictation, import, and live capture."""

    def transcribe_samples(
        self,
        samples: npt.NDArray[np.float32],
        *,
        stream: str,
        on_partial: Callable[[str], None] | None = None,
    ) -> list[SttSegment]: ...

    def transcribe_file(self, path: str) -> list[SttSegment]: ...
