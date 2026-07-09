"""Optional local Whisper STT via faster-whisper when installed."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE
from engine.stt.stt_backend_protocol import SttSegment


def _whisper_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


class WhisperSttBackend:
    def __init__(self, *, models_dir: Path | None = None, model_id: str = "tiny") -> None:
        self._model_id = model_id
        self._models_dir = models_dir
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ValueError(
                "Whisper backend requires faster-whisper (uv sync --extra whisper)"
            ) from exc
        download_root = str(self._models_dir) if self._models_dir is not None else None
        device = _whisper_device()
        compute_type = "float16" if device == "cuda" else "int8"
        self._model = WhisperModel(
            self._model_id,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
        return self._model

    def transcribe_samples(
        self,
        samples: npt.NDArray[np.float32],
        *,
        stream: str,
        on_partial: Callable[[str], None] | None = None,
    ) -> list[SttSegment]:
        model = self._load()
        segments_iter, _info = model.transcribe(  # type: ignore[union-attr]
            samples,
            language="en",
            vad_filter=True,
        )
        segments: list[SttSegment] = []
        partial_parts: list[str] = []
        for segment in segments_iter:
            text = segment.text.strip()
            if not text:
                continue
            partial_parts.append(text)
            if on_partial is not None:
                on_partial(" ".join(partial_parts))
            segments.append(
                SttSegment(
                    text=text,
                    t_start=float(segment.start),
                    t_end=float(segment.end),
                    stream=stream,
                )
            )
        return segments

    def transcribe_file(self, path: str) -> list[SttSegment]:
        model = self._load()
        segments_iter, _info = model.transcribe(str(path), vad_filter=True)  # type: ignore[union-attr]
        return [
            SttSegment(
                text=segment.text.strip(),
                t_start=float(segment.start),
                t_end=float(segment.end),
                stream="them",
            )
            for segment in segments_iter
            if segment.text.strip()
        ]
