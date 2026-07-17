"""``ollama.*`` command dispatch: list/pull/ping against the local Ollama host.

Purpose: the Settings surface for Meetily-style local summaries — list
installed models, pull a new one with real progress events, and ping the
host for a live "Test connection" check.
Pipeline position: driven by the connection handler via
``engine.wiring.onboarding_settings_command_surface``; talks to
``engine.router.ollama_http_client`` (thin HTTP helpers), never a raw URL
supplied by the client.

Security invariants:
- The base URL is resolved ENGINE-SIDE (``OMNI_OLLAMA_BASE_URL`` env or a
  loopback default) — never accepted from the client payload.
- Model names are shape-checked at the payload boundary and re-validated
  against an allowlisted charset by the HTTP client (defence in depth).
- One pull at a time: a second pull while one is in flight is refused,
  never allowed to race progress events against each other.
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from engine.protocol import (
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    ProtocolErrorCode,
    error_reply,
)
from engine.protocol.ollama_command_payloads import (
    COMMAND_OLLAMA_MODELS_LIST,
    COMMAND_OLLAMA_MODELS_PULL,
    COMMAND_OLLAMA_PING,
    EVENT_OLLAMA_PULL_COMPLETED,
    EVENT_OLLAMA_PULL_FAILED,
    EVENT_OLLAMA_PULL_PROGRESS,
    OllamaModelsListCommandPayload,
    OllamaModelsPullCommandPayload,
    OllamaPingCommandPayload,
    build_ollama_pull_completed_payload,
    build_ollama_pull_failed_payload,
    build_ollama_pull_progress_payload,
)
from engine.router.ollama_http_client import (
    list_ollama_models,
    normalize_ollama_base,
    ping_ollama,
    pull_ollama_model,
)

logger = logging.getLogger(__name__)

OLLAMA_COMMAND_NAMES = frozenset(
    {COMMAND_OLLAMA_MODELS_LIST, COMMAND_OLLAMA_MODELS_PULL, COMMAND_OLLAMA_PING}
)
OLLAMA_ERROR_CODE = "ollama_error"
# Same env var the router/provider-client registry reads (single source of
# truth for "where is Ollama") — kept as a literal here to avoid a
# router<->wiring import cycle; both must stay in lockstep on this name.
OLLAMA_BASE_URL_ENV = "OMNI_OLLAMA_BASE_URL"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"

SendFn = Callable[[Envelope], Awaitable[None]]
BaseUrlFn = Callable[[], str]


def _default_base_url() -> str:
    """The configured Ollama host, or the loopback default — never a
    client-supplied URL."""
    configured = os.environ.get(OLLAMA_BASE_URL_ENV, "").strip()
    return normalize_ollama_base(configured or DEFAULT_OLLAMA_BASE_URL)


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


def _ollama_error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": OLLAMA_ERROR_CODE, "message": message},
    )


class OllamaCommandGateway:
    """One per engine process; construction is inert (no network until asked)."""

    def __init__(self, hub: EventBroadcastHub, get_base_url: BaseUrlFn | None = None) -> None:
        self._hub = hub
        self._get_base_url = get_base_url if get_base_url is not None else _default_base_url
        self._pull_task: asyncio.Task[None] | None = None

    def is_pulling(self) -> bool:
        """True while a pull task is in flight (single-flight guard)."""
        return self._pull_task is not None and not self._pull_task.done()

    async def list_models(self) -> dict[str, object]:
        base = self._get_base_url()
        models = await asyncio.to_thread(list_ollama_models, base)
        return {"models": models}

    async def ping(self) -> dict[str, object]:
        base = self._get_base_url()
        return await asyncio.to_thread(ping_ollama, base)

    def begin_pull(self, model: str) -> bool:
        """Start the background pull. Returns False if one is already running."""
        if self.is_pulling():
            return False
        self._pull_task = asyncio.create_task(self._run_pull(model))
        return True

    async def _run_pull(self, model: str) -> None:
        """Run the blocking pull off-loop, streaming progress events as it goes."""
        loop = asyncio.get_running_loop()
        base = self._get_base_url()

        def on_progress(name: str, received: int, total: int | None) -> None:
            payload = build_ollama_pull_progress_payload(name, received, total)
            asyncio.run_coroutine_threadsafe(
                self._hub.broadcast_event(EVENT_OLLAMA_PULL_PROGRESS, payload), loop
            )

        try:
            await asyncio.to_thread(pull_ollama_model, base, model, on_progress)
        except Exception as exc:
            logger.exception("ollama.models.pull failed for %s", model)
            await self._hub.broadcast_event(
                EVENT_OLLAMA_PULL_FAILED, build_ollama_pull_failed_payload(model, str(exc)[:300])
            )
            return
        await self._hub.broadcast_event(
            EVENT_OLLAMA_PULL_COMPLETED, build_ollama_pull_completed_payload(model)
        )

    async def shutdown(self) -> None:
        """Cancel any in-flight pull so it never outlives the process."""
        if self._pull_task is not None and not self._pull_task.done():
            self._pull_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._pull_task


async def dispatch_ollama_command(
    command: Envelope, gateway: OllamaCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated ollama.* command, always replying (fail closed)."""
    if gateway is None:
        await send(_ollama_error_reply(command.id, "Ollama is not available"))
        return
    name = command.name
    if name == COMMAND_OLLAMA_MODELS_LIST:
        await _dispatch_list(command, gateway, send)
    elif name == COMMAND_OLLAMA_PING:
        await _dispatch_ping(command, gateway, send)
    elif name == COMMAND_OLLAMA_MODELS_PULL:
        await _dispatch_pull(command, gateway, send)


async def _dispatch_list(command: Envelope, gateway: OllamaCommandGateway, send: SendFn) -> None:
    try:
        OllamaModelsListCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "ollama.models.list payload failed validation",
            )
        )
        return
    try:
        result = await gateway.list_models()
    except Exception as exc:
        await send(_ollama_error_reply(command.id, f"could not list Ollama models: {exc}"))
        return
    await send(_ok_reply(command.id, result))


async def _dispatch_ping(command: Envelope, gateway: OllamaCommandGateway, send: SendFn) -> None:
    try:
        OllamaPingCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "ollama.ping payload failed validation",
            )
        )
        return
    result = await gateway.ping()
    await send(_ok_reply(command.id, result))


async def _dispatch_pull(command: Envelope, gateway: OllamaCommandGateway, send: SendFn) -> None:
    try:
        payload = OllamaModelsPullCommandPayload.model_validate(command.payload)
    except ValidationError as exc:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                f"ollama.models.pull payload failed validation: {exc.errors()[0]['msg']}",
            )
        )
        return
    started = gateway.begin_pull(payload.model)
    await send(_ok_reply(command.id, {"started": started, "model": payload.model}))
