"""Protocol v1 payloads for the M7 Google-connect command surface.

Purpose: pinned names and strict payload models for ``google.connect``
(fires the existing OAuth desktop loopback flow) and the completion event
the onboarding wizard / Settings render.
Pipeline position: consumed by
``engine.wiring.google_connect_command_dispatcher`` and the UI.

Security invariants:
- The client id/secret ride as pydantic ``SecretStr`` so validation errors
  and reprs can never echo them; they land in the DPAPI token store only.
- ``extra="forbid"`` — untrusted input, deny by default.
- Scopes are NOT part of the payload: they are pinned in
  ``engine.google.oauth_desktop_flow`` (calendar events, contacts, Gmail
  draft-compose — never send) and cannot be widened over the wire.
"""

from pydantic import BaseModel, ConfigDict, Field, SecretStr

COMMAND_GOOGLE_CONNECT = "google.connect"

EVENT_GOOGLE_CONNECT_COMPLETED = "google.connect.completed"

_MAX_CREDENTIAL_CHARS = 512


class GoogleConnectCommandPayload(BaseModel):
    """``google.connect`` — optionally carries fresh OAuth client
    credentials (user-suppliable in-app); omitted means "use what the DPAPI
    store / dev env already holds". Both-or-neither: a lone id or secret is
    rejected by the gateway."""

    model_config = ConfigDict(extra="forbid")

    client_id: SecretStr | None = Field(default=None, max_length=_MAX_CREDENTIAL_CHARS)
    client_secret: SecretStr | None = Field(default=None, max_length=_MAX_CREDENTIAL_CHARS)


def build_google_connect_completed_payload(ok: bool, message: str) -> dict[str, object]:
    """Honest outcome of the consent flow (no token material, ever)."""
    return {"ok": ok, "message": message}
