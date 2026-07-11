"""Protocol v1 payloads for the M7 model-download command + progress events.

Purpose: pinned names and shapes for ``models.download`` and the events the
onboarding wizard renders real progress bars from.
Pipeline position: consumed by
``engine.wiring.models_download_command_dispatcher`` and the UI.

Security: client supplies only allowlisted bundle/model_id — never a URL.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from engine.stt.whisper_model_catalog import WHISPER_MODEL_IDS

COMMAND_MODELS_DOWNLOAD = "models.download"

EVENT_MODELS_DOWNLOAD_PROGRESS = "models.download.progress"
EVENT_MODELS_DOWNLOAD_FAILED = "models.download.failed"
EVENT_MODELS_DOWNLOAD_COMPLETED = "models.download.completed"

_ALLOWED_BUNDLES = frozenset({"core", "whisper"})
_WHISPER_IDS = frozenset(WHISPER_MODEL_IDS)


class ModelsDownloadCommandPayload(BaseModel):
    """``models.download`` — core (Silero+Parakeet) or a Whisper ggml size."""

    model_config = ConfigDict(extra="forbid")

    bundle: str = "core"
    model_id: str | None = None

    @field_validator("bundle")
    @classmethod
    def _bundle_ok(cls, value: str) -> str:
        if value not in _ALLOWED_BUNDLES:
            raise ValueError("bundle must be 'core' or 'whisper'")
        return value

    @model_validator(mode="after")
    def _whisper_needs_id(self) -> ModelsDownloadCommandPayload:
        if self.bundle == "whisper":
            if self.model_id is None or self.model_id not in _WHISPER_IDS:
                raise ValueError(
                    "whisper bundle requires model_id from the Meetily ggml catalog"
                )
        return self


def build_models_download_progress_payload(
    file: str,
    received_bytes: int,
    total_bytes: int | None,
    sha256_verified: bool | None,
) -> dict[str, object]:
    """One progress beat during a download."""
    return {
        "file": file,
        "received_bytes": received_bytes,
        "total_bytes": total_bytes,
        "sha256_verified": sha256_verified,
    }


def build_models_download_failed_payload(file: str, message: str) -> dict[str, object]:
    """Honest failure for one file (the wizard offers retry)."""
    return {"file": file, "message": message}


def build_models_download_completed_payload(
    ok: bool, files: list[dict[str, object]]
) -> dict[str, object]:
    """End-of-run summary: per-file name/bytes/sha256/verified entries."""
    return {"ok": ok, "files": files}
