"""Protocol payloads for Microsoft / Outlook connect."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr

COMMAND_MICROSOFT_CONNECT = "microsoft.connect"
EVENT_MICROSOFT_CONNECT_COMPLETED = "microsoft.connect.completed"

_MAX_CREDENTIAL_CHARS = 512


class MicrosoftConnectCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: SecretStr | None = Field(default=None, max_length=_MAX_CREDENTIAL_CHARS)
    client_secret: SecretStr | None = Field(default=None, max_length=_MAX_CREDENTIAL_CHARS)


def build_microsoft_connect_completed_payload(ok: bool, message: str) -> dict[str, object]:
    return {"ok": ok, "message": message}
