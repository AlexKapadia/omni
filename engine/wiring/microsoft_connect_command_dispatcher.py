"""``microsoft.connect`` gateway + WS dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.microsoft.dpapi_microsoft_token_store import (
    MicrosoftOAuthClientCredentials,
    MicrosoftTokenStore,
)
from engine.microsoft.microsoft_auth_errors import MicrosoftError
from engine.microsoft.oauth_desktop_flow import run_microsoft_oauth_desktop_flow
from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    ProtocolErrorCode,
    error_reply,
)
from engine.protocol.microsoft_connect_payloads import (
    COMMAND_MICROSOFT_CONNECT,
    EVENT_MICROSOFT_CONNECT_COMPLETED,
    MicrosoftConnectCommandPayload,
    build_microsoft_connect_completed_payload,
)

logger = logging.getLogger(__name__)

MICROSOFT_COMMAND_NAMES = frozenset({COMMAND_MICROSOFT_CONNECT})
MICROSOFT_ERROR_CODE = "microsoft_error"

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _microsoft_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": MICROSOFT_ERROR_CODE, "message": message},
    )


class MicrosoftConnectCommandGateway:
    def __init__(self, hub: EventBroadcastHub, token_store: MicrosoftTokenStore | None = None) -> None:
        self._hub = hub
        self._token_store = token_store if token_store is not None else MicrosoftTokenStore()
        self._task: asyncio.Task[None] | None = None

    def is_connecting(self) -> bool:
        return self._task is not None and not self._task.done()

    def begin_connect(self, client_id: str | None, client_secret: str | None) -> bool:
        if self.is_connecting():
            return False
        if client_id is not None and client_secret is not None:
            self._token_store.save_client_credentials(
                MicrosoftOAuthClientCredentials(client_id, client_secret)
            )
        self._task = asyncio.create_task(self._run_connect())
        return True

    async def _run_connect(self) -> None:
        try:
            await run_microsoft_oauth_desktop_flow(self._token_store)
        except MicrosoftError as exc:
            await self._hub.broadcast_event(
                EVENT_MICROSOFT_CONNECT_COMPLETED,
                build_microsoft_connect_completed_payload(ok=False, message=str(exc)),
            )
            return
        except Exception:
            logger.exception("microsoft.connect flow failed")
            await self._hub.broadcast_event(
                EVENT_MICROSOFT_CONNECT_COMPLETED,
                build_microsoft_connect_completed_payload(
                    ok=False, message="the Microsoft connection did not complete"
                ),
            )
            return
        await self._hub.broadcast_event(
            EVENT_MICROSOFT_CONNECT_COMPLETED,
            build_microsoft_connect_completed_payload(ok=True, message="Microsoft is connected"),
        )

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task


async def dispatch_microsoft_command(
    command: Envelope, gateway: MicrosoftConnectCommandGateway | None, send: SendFn
) -> None:
    if gateway is None:
        await send(_microsoft_error_reply(command.id, "Microsoft connect is not available"))
        return
    try:
        payload = MicrosoftConnectCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "microsoft.connect payload failed validation",
            )
        )
        return
    client_id = payload.client_id.get_secret_value() if payload.client_id is not None else None
    client_secret = (
        payload.client_secret.get_secret_value() if payload.client_secret is not None else None
    )
    if (client_id is None) != (client_secret is None):
        await send(
            _microsoft_error_reply(command.id, "provide both the client id and secret, or neither")
        )
        return
    started = gateway.begin_connect(client_id, client_secret)
    await send(_ok_reply(command.id, {"started": started}))
