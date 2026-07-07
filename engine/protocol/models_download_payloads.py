"""Protocol v1 payloads for the M7 model-download command + progress events.

Purpose: pinned names and shapes for ``models.download`` and the events the
onboarding wizard renders real progress bars from:
``models.download.progress`` {file, received_bytes, total_bytes,
sha256_verified}, ``models.download.failed`` {file, message}, and
``models.download.completed`` {ok, files}.
Pipeline position: consumed by
``engine.wiring.models_download_command_dispatcher`` (validation + emission)
and the UI (shape contract).

Security invariant: the command payload is untrusted input
(``extra="forbid"``); download sources stay the PINNED first-party HTTPS
URLs in ``engine.stt.model_weights_downloader`` — the client can never
supply a URL.
"""

from pydantic import BaseModel, ConfigDict

COMMAND_MODELS_DOWNLOAD = "models.download"

EVENT_MODELS_DOWNLOAD_PROGRESS = "models.download.progress"
EVENT_MODELS_DOWNLOAD_FAILED = "models.download.failed"
EVENT_MODELS_DOWNLOAD_COMPLETED = "models.download.completed"


class ModelsDownloadCommandPayload(BaseModel):
    """``models.download`` takes no arguments (the model set is pinned);
    present files are re-verified (hashed) rather than re-fetched, so the
    same command is also the retry AND the integrity-check path."""

    model_config = ConfigDict(extra="forbid")


def build_models_download_progress_payload(
    file: str,
    received_bytes: int,
    total_bytes: int | None,
    sha256_verified: bool | None,
) -> dict[str, object]:
    """One progress beat. ``total_bytes`` is None until the server says;
    ``sha256_verified`` is None while downloading, then the honest verify
    outcome (True only when the hash matches the pinned manifest)."""
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
