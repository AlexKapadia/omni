"""Parakeet on-device STT backend."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.stt.offline_audio_transcriber import (
    OfflineSegment,
    load_transcriber,
    transcribe_samples,
)
from engine.stt.stt_backend_protocol import SttSegment


class ParakeetSttBackend:
    def __init__(self, *, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir
        self._transcriber = load_transcriber(models_dir)

    def transcribe_samples(
        self,
        samples: npt.NDArray[np.float32],
        *,
        stream: str,
        on_partial: Callable[[str], None] | None = None,
    ) -> list[SttSegment]:
        if on_partial is not None:
            on_partial("")
        segments = transcribe_samples(self._transcriber, samples, stream=stream)
        return [_to_stt_segment(segment) for segment in segments]

    def transcribe_file(self, path: str) -> list[SttSegment]:
        from engine.stt.offline_audio_transcriber import decode_media_to_mono_16k

        samples = decode_media_to_mono_16k(Path(path))
        return self.transcribe_samples(samples, stream="them")


def _to_stt_segment(segment: OfflineSegment) -> SttSegment:
    return SttSegment(
        text=segment.text,
        t_start=segment.t_start,
        t_end=segment.t_end,
        stream=segment.stream,
    )
