"""Payload model for the ``selection.translate`` command."""

from pydantic import BaseModel, ConfigDict, Field

MAX_SELECTION_TRANSLATE_CHARS = 8000


class SelectionTranslateCommandPayload(BaseModel):
    """Payload of the ``selection.translate`` command (client -> engine)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_SELECTION_TRANSLATE_CHARS)
    target_lang: str | None = Field(default=None, max_length=64)
