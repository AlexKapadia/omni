"""Protocol v1 payloads for the M7 model-lifecycle commands (cancel/delete/open).

Purpose: pinned names and shapes for managing already-downloaded (or
in-flight) on-device model weights from Settings — cancel a running
download, delete one file, or reveal the models folder in Explorer.
Pipeline position: consumed by
``engine.wiring.models_download_command_dispatcher`` and the UI.

Security: ``models.delete`` accepts a bare filename only (basename, no path
separators) — the dispatcher resolves it under the models directory and
refuses anything that would escape it (path-traversal defence).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

COMMAND_MODELS_CANCEL = "models.cancel"
COMMAND_MODELS_DELETE = "models.delete"
COMMAND_MODELS_OPEN_FOLDER = "models.open_folder"

_MAX_FILENAME_CHARS = 255


class ModelsCancelCommandPayload(BaseModel):
    """``models.cancel`` takes no arguments; extras are rejected."""

    model_config = ConfigDict(extra="forbid")


class ModelsDeleteCommandPayload(BaseModel):
    """``models.delete`` — a bare filename (basename only, no path separators)."""

    model_config = ConfigDict(extra="forbid")

    file: str

    @field_validator("file")
    @classmethod
    def _file_ok(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed or len(trimmed) > _MAX_FILENAME_CHARS:
            raise ValueError("file must be a non-empty filename")
        # Deny by default: any path separator or traversal token is refused
        # here, before the dispatcher even resolves a path (defence in depth).
        if "/" in trimmed or "\\" in trimmed or ".." in trimmed:
            raise ValueError("file must be a bare filename, not a path")
        return trimmed


class ModelsOpenFolderCommandPayload(BaseModel):
    """``models.open_folder`` takes no arguments; extras are rejected."""

    model_config = ConfigDict(extra="forbid")
