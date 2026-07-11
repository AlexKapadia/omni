"""models.download payload: core vs whisper bundle (allowlisted ids only)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.protocol.models_download_payloads import ModelsDownloadCommandPayload


def test_empty_payload_defaults_to_core_bundle() -> None:
    payload = ModelsDownloadCommandPayload.model_validate({})
    assert payload.bundle == "core"
    assert payload.model_id is None


def test_whisper_bundle_requires_allowlisted_model_id() -> None:
    with pytest.raises(ValidationError):
        ModelsDownloadCommandPayload.model_validate({"bundle": "whisper"})
    with pytest.raises(ValidationError):
        ModelsDownloadCommandPayload.model_validate(
            {"bundle": "whisper", "model_id": "not-a-real-size"}
        )


@pytest.mark.parametrize(
    "model_id",
    ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "medium-q5_0"],
)
def test_whisper_bundle_accepts_allowlisted_ids(model_id: str) -> None:
    payload = ModelsDownloadCommandPayload.model_validate(
        {"bundle": "whisper", "model_id": model_id}
    )
    assert payload.bundle == "whisper"
    assert payload.model_id == model_id


def test_unknown_bundle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelsDownloadCommandPayload.model_validate({"bundle": "gguf"})
