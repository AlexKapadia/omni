"""``speaker.enroll`` command payloads."""

from pydantic import BaseModel, ConfigDict, Field

COMMAND_SPEAKER_ENROLL = "speaker.enroll"


class SpeakerEnrollCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=64)
    audio_wav_base64: str | None = Field(default=None, max_length=2_000_000)
