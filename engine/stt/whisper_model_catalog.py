"""Whisper (ggml / whisper.cpp) catalog — Meetily-compatible model list.

Purpose: Settings downloads the same ``ggml-*.bin`` files Meetily uses from
Hugging Face ``ggerganov/whisper.cpp``. Live + import STT load them via
pywhispercpp.
Pipeline position: ``models.download`` when ``bundle=whisper``; presence
rows in ``setup.status``.

Security: HTTPS Hugging Face only; client supplies an allowlisted model id,
never a URL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.stt.model_weights_downloader import FetchFn, _https_fetch


# Meetily WHISPER_MODEL_CATALOG (name, filename, size_mb, accuracy, speed, description)
@dataclass(frozen=True)
class WhisperModelSpec:
    """One Meetily-compatible ggml Whisper size."""

    model_id: str
    filename: str
    size_mb: int
    accuracy: str
    speed: str
    description: str
    basic: bool  # shown outside the Advanced accordion in Settings


WHISPER_MODEL_SPECS: tuple[WhisperModelSpec, ...] = (
    WhisperModelSpec(
        "tiny", "ggml-tiny.bin", 74, "Decent", "Very Fast", "Fastest processing", False
    ),
    WhisperModelSpec(
        "base",
        "ggml-base.bin",
        142,
        "Good",
        "Fast",
        "Good balance of speed and accuracy",
        False,
    ),
    WhisperModelSpec(
        "small",
        "ggml-small.bin",
        466,
        "Good",
        "Medium",
        "Better accuracy, moderate speed",
        True,
    ),
    WhisperModelSpec(
        "medium",
        "ggml-medium.bin",
        1463,
        "High",
        "Slow",
        "High accuracy for professional use",
        False,
    ),
    WhisperModelSpec(
        "large-v3-turbo",
        "ggml-large-v3-turbo.bin",
        1549,
        "High",
        "Medium",
        "Best accuracy with improved speed",
        True,
    ),
    WhisperModelSpec(
        "large-v3", "ggml-large-v3.bin", 2951, "High", "Slow", "Most accurate large model", True
    ),
    WhisperModelSpec(
        "tiny-q5_1", "ggml-tiny-q5_1.bin", 31, "Decent", "Very Fast", "Quantized tiny", False
    ),
    WhisperModelSpec(
        "base-q5_1", "ggml-base-q5_1.bin", 57, "Good", "Fast", "Quantized base", False
    ),
    WhisperModelSpec(
        "small-q5_1", "ggml-small-q5_1.bin", 181, "Good", "Fast", "Quantized small", False
    ),
    WhisperModelSpec(
        "medium-q5_0", "ggml-medium-q5_0.bin", 514, "High", "Medium", "Quantized medium", True
    ),
    WhisperModelSpec(
        "large-v3-turbo-q5_0",
        "ggml-large-v3-turbo-q5_0.bin",
        547,
        "High",
        "Medium",
        "Quantized large turbo",
        False,
    ),
    WhisperModelSpec(
        "large-v3-q5_0", "ggml-large-v3-q5_0.bin", 1031, "High", "Slow", "Quantized large", True
    ),
)

WHISPER_MODEL_IDS: tuple[str, ...] = tuple(s.model_id for s in WHISPER_MODEL_SPECS)
WHISPER_MODEL_BY_ID: dict[str, WhisperModelSpec] = {s.model_id: s for s in WHISPER_MODEL_SPECS}
DEFAULT_WHISPER_MODEL_ID = "large-v3-turbo"

_HF_WHISPER_CPP = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


def whisper_ggml_filename(model_id: str) -> str:
    spec = WHISPER_MODEL_BY_ID.get(model_id)
    if spec is None:
        raise ValueError(f"unsupported Whisper model id: {model_id}")
    return spec.filename


def whisper_model_path(models_dir: Path, model_id: str) -> Path:
    return models_dir / whisper_ggml_filename(model_id)


def whisper_download_url(model_id: str) -> str:
    return f"{_HF_WHISPER_CPP}/{whisper_ggml_filename(model_id)}"


def is_whisper_model_present(models_dir: Path, model_id: str) -> bool:
    path = whisper_model_path(models_dir, model_id)
    if not path.is_file():
        return False
    # Refuse empty stubs; real ggml bins are multi-MB.
    return path.stat().st_size > 1000


def whisper_models_status(models_dir: Path) -> list[dict[str, object]]:
    """Presence rows for ``setup.status`` (optional Enhanced / live Whisper)."""
    rows: list[dict[str, object]] = []
    for spec in WHISPER_MODEL_SPECS:
        present = is_whisper_model_present(models_dir, spec.model_id)
        size = whisper_model_path(models_dir, spec.model_id).stat().st_size if present else 0
        rows.append({"file": spec.filename, "present": present, "bytes": size})
    return rows


ProgressFn = Callable[[str, int, int | None, bool | None], None]


def download_whisper_model(
    model_id: str,
    models_dir: Path,
    on_progress: ProgressFn,
    fetch: FetchFn = _https_fetch,
) -> dict[str, object]:
    """Download one Meetily-compatible ggml Whisper bin into ``models_dir``."""
    if model_id not in WHISPER_MODEL_BY_ID:
        raise ValueError(f"unsupported Whisper model id: {model_id}")
    models_dir.mkdir(parents=True, exist_ok=True)
    filename = whisper_ggml_filename(model_id)
    target = models_dir / filename

    if is_whisper_model_present(models_dir, model_id):
        size = target.stat().st_size
        on_progress(filename, size, size, True)
        return {"file": filename, "bytes": size, "sha256": "", "sha256_verified": False}

    on_progress(filename, 0, None, None)
    partial = target.with_suffix(target.suffix + ".partial")
    if partial.exists():
        partial.unlink()

    def _beat(received: int, total: int | None) -> None:
        on_progress(filename, received, total, None)

    fetch(whisper_download_url(model_id), partial, _beat)
    partial.replace(target)
    size = target.stat().st_size
    on_progress(filename, size, size, False)
    return {"file": filename, "bytes": size, "sha256": "", "sha256_verified": False}
