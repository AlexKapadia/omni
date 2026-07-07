"""``google.connect`` gateway + WS dispatch: the desktop OAuth consent flow.

Purpose: the server-layer surface the onboarding wizard / Settings drive to
connect a Google account. Optionally accepts fresh OAuth client credentials
(user-suppliable in-app), persists them DPAPI-encrypted, then runs the
existing loopback PKCE consent flow in the background and reports the
outcome via ``google.connect.completed``. The step is skippable — declining
it never blocks setup.
Pipeline position: driven by the connection handler for ``google.connect``;
runs ``engine.google.oauth_desktop_flow`` off the reply path.

Security invariants (claude.md §5.6):
- Client id/secret ride as ``SecretStr`` and land in the DPAPI token store
  ONLY; they are never logged or echoed. Scopes are pinned in the flow
  (calendar events, contacts, Gmail draft-compose — never send) and cannot
  be widened over the wire.
- Both-or-neither: a lone id or secret is refused (deny by default).
- The consent flow fails closed on every error; token material never rides
  the completion event (ok + a plain message only).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.google.dpapi_google_token_store import (
    GoogleOAuthClientCredentials,
    GoogleTokenStore,
)
from engine.google.google_auth_errors import GoogleError
from engine.google.oauth_desktop_flow import run_google_oauth_desktop_flow
from engine.protocol import (
    COMMAND_GOOGLE_CONNECT,
    EVENT_GOOGLE_CONNECT_COMPLETED,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    GoogleConnectCommandPayload,
    ProtocolErrorCode,
    build_google_connect_completed_payload,
    error_reply,
)

logger = logging.getLogger(__name__)

GOOGLE_COMMAND_NAMES = frozenset({COMMAND_GOOGLE_CONNECT})

GOOGLE_ERROR_CODE = "google_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _google_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": GOOGLE_ERROR_CODE, "message": message},
    )


class GoogleConnectCommandGateway:
    """One per engine process; construction is inert (no I/O, no browser)."""

    def __init__(self, hub: EventBroadcastHub, token_store: GoogleTokenStore | None = None) -> None:
        self._hub = hub
        self._token_store = token_store if token_store is not None else GoogleTokenStore()
        self._task: asyncio.Task[None] | None = None

    def is_connecting(self) -> bool:
        """True while a consent flow is in flight (single-flight guard)."""
        return self._task is not None and not self._task.done()

    def begin_connect(self, client_id: str | None, client_secret: str | None) -> bool:
        """Persist fresh credentials (if given) and start the flow in the
        background. Returns False if a flow is already running."""
        if self.is_connecting():
            return False
        if client_id is not None and client_secret is not None:
            # Credentials land in the DPAPI store only; never logged.
            self._token_store.save_client_credentials(
                GoogleOAuthClientCredentials(client_id, client_secret)
            )
        self._task = asyncio.create_task(self._run_connect())
        return True

    async def _run_connect(self) -> None:
        """Run the consent flow, emitting the honest completion event."""
        try:
            await run_google_oauth_desktop_flow(self._token_store)
        except GoogleError as exc:
            # Fail closed with a plain reason; no token or credential material.
            await self._hub.broadcast_event(
                EVENT_GOOGLE_CONNECT_COMPLETED,
                build_google_connect_completed_payload(ok=False, message=str(exc)),
            )
            return
        except Exception:
            logger.exception("google.connect flow failed")
            await self._hub.broadcast_event(
                EVENT_GOOGLE_CONNECT_COMPLETED,
                build_google_connect_completed_payload(
                    ok=False, message="the Google connection did not complete"
                ),
            )
            return
        await self._hub.broadcast_event(
            EVENT_GOOGLE_CONNECT_COMPLETED,
            build_google_connect_completed_payload(ok=True, message="Google is connected"),
        )

    async def shutdown(self) -> None:
        """Cancel an in-flight consent flow so it never outlives the process."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task


async def dispatch_google_command(
    command: Envelope, gateway: GoogleConnectCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated google.connect command, always replying (fail closed)."""
    if gateway is None:
        await send(_google_error_reply(command.id, "Google connect is not available"))
        return
    try:
        payload = GoogleConnectCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "google.connect payload failed validation",
            )
        )
        return
    client_id = payload.client_id.get_secret_value() if payload.client_id is not None else None
    client_secret = (
        payload.client_secret.get_secret_value() if payload.client_secret is not None else None
    )
    # Both-or-neither: a lone id or secret is an invalid request (deny default).
    if (client_id is None) != (client_secret is None):
        await send(
            _google_error_reply(command.id, "provide both the client id and secret, or neither")
        )
        return
    started = gateway.begin_connect(client_id, client_secret)
    # Accepted-immediately: the outcome arrives as google.connect.completed.
    await send(_ok_reply(command.id, {"started": started}))
