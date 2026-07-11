"""Protocol v1 payloads for the ``ollama.*`` commands (Meetily-style local models).

Purpose: pinned names and shapes for listing/pulling local Ollama models and
pinging the host, so Settings can drive real progress bars and an honest
"Test connection" check.
Pipeline position: consumed by ``engine.wiring.ollama_command_dispatcher``.

Security: no URL ever rides the wire from the client — the base URL is
resolved engine-side. Model names get a light shape check here; the HTTP
client (``engine.router.ollama_http_client``) re-validates against its own
allowlisted charset before any network call (defence in depth).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

COMMAND_OLLAMA_MODELS_LIST = "ollama.models.list"
COMMAND_OLLAMA_MODELS_PULL = "ollama.models.pull"
COMMAND_OLLAMA_PING = "ollama.ping"

EVENT_OLLAMA_PULL_PROGRESS = "ollama.pull.progress"
EVENT_OLLAMA_PULL_COMPLETED = "ollama.pull.completed"
EVENT_OLLAMA_PULL_FAILED = "ollama.pull.failed"

_MAX_MODEL_NAME_CHARS = 128


class OllamaModelsListCommandPayload(BaseModel):
    """``ollama.models.list`` takes no arguments; extras are rejected."""

    model_config = ConfigDict(extra="forbid")


class OllamaModelsPullCommandPayload(BaseModel):
    """``ollama.models.pull`` — the model tag to pull, e.g. ``llama3.2``."""

    model_config = ConfigDict(extra="forbid")

    model: str

    @field_validator("model")
    @classmethod
    def _model_ok(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed or len(trimmed) > _MAX_MODEL_NAME_CHARS:
            raise ValueError("model must be a non-empty model name")
        return trimmed


class OllamaPingCommandPayload(BaseModel):
    """``ollama.ping`` takes no arguments; extras are rejected."""

    model_config = ConfigDict(extra="forbid")


def build_ollama_pull_progress_payload(
    model: str, received_bytes: int, total_bytes: int | None
) -> dict[str, object]:
    """One progress beat during a pull."""
    return {"model": model, "received_bytes": received_bytes, "total_bytes": total_bytes}


def build_ollama_pull_completed_payload(model: str) -> dict[str, object]:
    """The pull finished successfully."""
    return {"model": model, "ok": True}


def build_ollama_pull_failed_payload(model: str, message: str) -> dict[str, object]:
    """Honest per-model failure (the UI offers retry)."""
    return {"model": model, "message": message}
