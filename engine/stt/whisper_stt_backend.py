"""Optional local Whisper STT via whisper.cpp (pywhispercpp) on ggml bins."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt

from engine.stt.stt_backend_protocol import SttSegment
from engine.stt.word_token_types import WordToken


class _WhisperModel(Protocol):
    def transcribe(self, audio: object, **kwargs: object) -> object: ...


class WhisperSttBackend:
    """Meetily-compatible ggml Whisper via pywhispercpp."""

    def __init__(self, *, models_dir: Path | None = None, model_id: str = "tiny") -> None:
        self._model_id = model_id
        self._models_dir = models_dir
        self._model: _WhisperModel | None = None

    def _ggml_path(self) -> Path:
        from engine.stt.whisper_model_catalog import (
            is_whisper_model_present,
            whisper_model_path,
        )

        if self._models_dir is None:
            raise ValueError("Whisper backend requires models_dir for ggml weights")
        if not is_whisper_model_present(self._models_dir, self._model_id):
            raise ValueError(
                f"Whisper model {self._model_id!r} is not installed — "
                "download it from Settings → Transcription"
            )
        return whisper_model_path(self._models_dir, self._model_id)

    def _load(self) -> _WhisperModel:
        if self._model is not None:
            return self._model
        try:
            from pywhispercpp.model import Model
        except ImportError as exc:
            raise ValueError(
                "Whisper backend requires pywhispercpp (uv sync --extra whisper)"
            ) from exc
        path = self._ggml_path()
        self._model = cast(
            _WhisperModel,
            Model(
                str(path),
                print_progress=False,
                print_realtime=False,
                print_timestamps=False,
                language="en",
            ),
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
        segments_raw = cast(list[object], model.transcribe(samples))
        segments: list[SttSegment] = []
        partial_parts: list[str] = []
        for segment in segments_raw:
            text = str(getattr(segment, "text", "")).strip()
            if not text:
                continue
            partial_parts.append(text)
            if on_partial is not None:
                on_partial(" ".join(partial_parts))
            t0 = float(getattr(segment, "t0", 0)) / 100.0
            t1 = float(getattr(segment, "t1", 0)) / 100.0
            segments.append(SttSegment(text=text, t_start=t0, t_end=t1, stream=stream))
        return segments

    def transcribe_file(self, path: str) -> list[SttSegment]:
        model = self._load()
        segments_raw = cast(list[object], model.transcribe(path))
        return [
            SttSegment(
                text=str(getattr(segment, "text", "")).strip(),
                t_start=float(getattr(segment, "t0", 0)) / 100.0,
                t_end=float(getattr(segment, "t1", 0)) / 100.0,
                stream="them",
            )
            for segment in segments_raw
            if str(getattr(segment, "text", "")).strip()
        ]

    def transcribe_window(self, samples: npt.NDArray[np.float32]) -> list[WordToken]:
        """Live-capture seam: approximate word tokens from segment timestamps."""
        model = self._load()
        segments_raw = cast(list[object], model.transcribe(samples))
        words: list[WordToken] = []
        for segment in segments_raw:
            text = str(getattr(segment, "text", "")).strip()
            if not text:
                continue
            t0 = float(getattr(segment, "t0", 0)) / 100.0
            t1 = float(getattr(segment, "t1", 0)) / 100.0
            pieces = text.split()
            if not pieces:
                continue
            span = max(t1 - t0, 0.01)
            step = span / len(pieces)
            for i, piece in enumerate(pieces):
                start = t0 + i * step
                words.append(WordToken(text=piece, t_start=start, t_end=start + step))
        return words

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        self._load()
