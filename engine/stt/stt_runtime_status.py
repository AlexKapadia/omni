"""Runtime STT status surfaced in heartbeats and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "SttRuntimeStatus",
    "detect_inference_device",
    "get_stt_runtime_status",
    "update_stt_runtime_status",
]


@dataclass(frozen=True)
class SttRuntimeStatus:
    engine: str = "parakeet"
    model_id: str = ""
    device: str = "cpu"


_STATUS = SttRuntimeStatus()


def detect_inference_device() -> str:
    """Best-effort CUDA vs CPU for the active local inference stack."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def get_stt_runtime_status() -> SttRuntimeStatus:
    return _STATUS


def update_stt_runtime_status(
    *,
    engine: str | None = None,
    model_id: str | None = None,
    device: str | None = None,
) -> None:
    global _STATUS
    _STATUS = SttRuntimeStatus(
        engine=engine if engine is not None else _STATUS.engine,
        model_id=model_id if model_id is not None else _STATUS.model_id,
        device=device if device is not None else _STATUS.device,
    )
