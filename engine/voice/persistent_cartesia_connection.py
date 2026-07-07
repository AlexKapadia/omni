"""Persistent multiplexed Cartesia WebSocket — the warm-TTFA fix (brief §7).

Purpose: holds ONE long-lived Cartesia TTS WebSocket across utterances so a
turn's time-to-first-audio never pays the TLS+WSS handshake again. Each
utterance is a ``context_id`` multiplexed over the shared socket; clause
chunks ride ``continue:true`` frames with the last chunk ``continue:false``.
A dead socket (idle server close, network drop) is detected by the reader
pump and the NEXT utterance reconnects with capped exponential backoff.
Pipeline position: owned by ``engine.naomi.naomi_turn_speaker``; sits beside
``cartesia_streaming_tts_client`` (the one-shot dev-path client) as the
conversation-loop transport.

Security invariants (claude.md §5.6 project bindings):
- Kill switch checked at EVERY (re)connect attempt — engaged means no new
  socket is ever opened (fail closed on egress); an already-open socket is
  not used either: speak checks before sending.
- The API key is revealed only into the connection header; every error
  string is scrubbed with redact_secret_material before it propagates.
- Inbound provider frames are untrusted: parsed fail-closed; frames for
  unknown context_ids are dropped, never surfaced.
- Keepalive is protocol-level ping/pong (websockets ``ping_interval``), per
  Cartesia's guidance to keep idle sockets alive; a server-side idle close
  is handled as an honest reconnect, never an error surfaced to the user.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from engine.security import kill_switch_engaged, redact_secret_material
from engine.voice.cartesia_credentials import (
    CartesiaCredentials,
    load_cartesia_credentials,
)
from engine.voice.cartesia_message_framing import (
    CARTESIA_API_VERSION,
    CARTESIA_WSS_URL,
    CartesiaDone,
    CartesiaErrorMessage,
    CartesiaMessage,
    build_cancel_request,
    build_generation_request,
    parse_cartesia_message,
)
from engine.voice.cartesia_streaming_tts_client import WsConnectionLike
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

# Capped exponential backoff between reconnect attempts after a failure.
BACKOFF_SCHEDULE_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
_CONNECT_TIMEOUT_SECONDS = 10.0
# Protocol-level keepalive: ping every 20 s so NATs and the provider's idle
# reaper see a live socket (Cartesia guidance; websockets default cadence).
KEEPALIVE_PING_INTERVAL_SECONDS = 20.0
# Bound how long one utterance may wait for the provider's next frame — a
# black-holed stream must never hang a turn forever.
_RECEIVE_TIMEOUT_SECONDS = 30.0

ConnectFactory = Callable[[], Awaitable[WsConnectionLike]]
SleepFn = Callable[[float], Awaitable[None]]

# Reader-pump sentinel: the socket died under this utterance.
_CONNECTION_LOST = None


class PersistentCartesiaConnection:
    """One warm socket, many utterances; reconnects lazily on next use."""

    def __init__(
        self,
        credentials_loader: Callable[[], CartesiaCredentials] = load_cartesia_credentials,
        connect_factory: ConnectFactory | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._credentials_loader = credentials_loader
        self._connect_factory = connect_factory
        self._sleep = sleep
        self._credentials: CartesiaCredentials | None = None
        self._ws: WsConnectionLike | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()
        # Per-utterance inboxes, keyed by context_id (multiplexing seam).
        self._context_queues: dict[str, asyncio.Queue[CartesiaMessage | None]] = {}
        self._consecutive_connect_failures = 0

    @property
    def is_connected(self) -> bool:
        """True while a socket is believed live (the warm state)."""
        return self._ws is not None

    async def _connect(self) -> WsConnectionLike:
        if self._connect_factory is not None:
            return await self._connect_factory()
        # Lazy import: the engine (and hermetic tests) load without opening
        # any network machinery.
        import websockets

        credentials = self._credentials
        if credentials is None:  # pragma: no cover - guarded by caller
            raise VoiceProviderError("credentials not resolved before connect")
        url = f"{CARTESIA_WSS_URL}?cartesia_version={CARTESIA_API_VERSION}"
        return await websockets.connect(
            url,
            # The ONE place the key is revealed — straight into the header.
            additional_headers={"X-API-Key": credentials.api_key.reveal()},
            open_timeout=_CONNECT_TIMEOUT_SECONDS,
            ping_interval=KEEPALIVE_PING_INTERVAL_SECONDS,  # idle keepalive
        )

    async def _ensure_connected(self) -> WsConnectionLike:
        """Return the live socket, (re)connecting with backoff if needed."""
        async with self._connect_lock:
            if self._ws is not None:
                return self._ws
            # Kill-switch gate at EVERY (re)connect: engaged means the socket
            # is never opened (fail closed on egress — §5.6 binding).
            if kill_switch_engaged():
                raise VoiceEgressBlockedError()
            if self._credentials is None:
                self._credentials = self._credentials_loader()  # may raise NotConfigured
            if self._consecutive_connect_failures > 0:
                index = min(
                    self._consecutive_connect_failures - 1,
                    len(BACKOFF_SCHEDULE_SECONDS) - 1,
                )
                await self._sleep(BACKOFF_SCHEDULE_SECONDS[index])
                # Re-check after the wait: the switch may have been engaged
                # while we were backing off (fail closed, always current).
                if kill_switch_engaged():
                    raise VoiceEgressBlockedError()
            try:
                ws = await self._connect()
            except VoiceEgressBlockedError:
                raise
            except Exception as exc:
                self._consecutive_connect_failures += 1
                # `from None`: the raw exception may echo request headers.
                raise VoiceProviderError(
                    self._redact(f"cartesia connect failed: {exc}")
                ) from None
            self._consecutive_connect_failures = 0
            self._ws = ws
            self._reader_task = asyncio.create_task(self._reader_pump(ws))
            return ws

    async def _reader_pump(self, ws: WsConnectionLike) -> None:
        """Route inbound frames to their utterance queue until the socket dies."""
        try:
            # A torn socket (idle close, network drop) surfaces as an
            # exception here; we suppress it and fall through to the honest
            # cleanup in `finally`, which wakes every waiter and marks the
            # socket dead so the NEXT utterance reconnects. CancelledError is
            # a BaseException, so it is NOT suppressed by suppress(Exception)
            # — cancellation propagates but STILL runs the finally cleanup.
            with contextlib.suppress(Exception):
                while True:
                    raw = await ws.recv()
                    message = parse_cartesia_message(raw)
                    if message is None:
                        continue  # untrusted/undecodable frame: drop, never crash
                    queue = self._context_queues.get(message.context_id)
                    if queue is not None:
                        queue.put_nowait(message)
                    # Unknown context: a finished/cancelled utterance's
                    # stragglers or a foreign frame — dropped (deny by default).
        finally:
            if self._ws is ws:
                self._ws = None  # next utterance reconnects
            for queue in self._context_queues.values():
                queue.put_nowait(_CONNECTION_LOST)  # wake every waiter honestly

    async def speak_utterance(
        self,
        chunks: Sequence[str],
        context_id: str,
        affect: tuple[float, float] | None,
    ) -> AsyncIterator[CartesiaMessage]:
        """Stream one utterance (clause chunks) over the warm socket.

        Sends every chunk immediately — all but the last with
        ``continue:true`` — then yields this context's messages until done.
        Raises VoiceEgressBlockedError before any egress when the kill
        switch is engaged, and VoiceProviderError (redacted) on transport
        failure; a failure marks the socket dead so the next call reconnects.
        """
        if not chunks:
            raise ValueError("speak_utterance requires at least one text chunk")
        ws = await self._ensure_connected()
        queue: asyncio.Queue[CartesiaMessage | None] = asyncio.Queue()
        self._context_queues[context_id] = queue
        try:
            credentials = self._credentials
            if credentials is None:  # pragma: no cover - set by _ensure_connected
                raise VoiceProviderError("credentials missing after connect")
            try:
                last_index = len(chunks) - 1
                for index, chunk in enumerate(chunks):
                    await ws.send(
                        build_generation_request(
                            chunk,
                            context_id,
                            credentials.voice_id,
                            affect,
                            continue_transcript=index < last_index,
                        )
                    )
            except Exception as exc:
                await self._mark_dead(ws)
                raise VoiceProviderError(
                    self._redact(f"cartesia send failed: {exc}")
                ) from None
            while True:
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=_RECEIVE_TIMEOUT_SECONDS
                    )
                except TimeoutError:
                    await self._mark_dead(ws)
                    raise VoiceProviderError(
                        "cartesia stream stalled (no frame within the receive budget)"
                    ) from None
                if message is _CONNECTION_LOST or message is None:
                    raise VoiceProviderError("cartesia connection lost mid-utterance")
                yield message
                if isinstance(message, CartesiaDone | CartesiaErrorMessage):
                    return
        finally:
            self._context_queues.pop(context_id, None)

    async def cancel(self, context_id: str) -> bool:
        """Send the cancel frame for one context (the barge-in wire).

        Returns False when there is no live socket or the send fails — a
        torn socket means generation is already dead (silence achieved).
        """
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(build_cancel_request(context_id))
            return True
        except Exception:
            await self._mark_dead(ws)
            return False

    async def close(self) -> None:
        """Process shutdown: stop the pump and close the socket."""
        ws = self._ws
        self._ws = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
            self._reader_task = None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _mark_dead(self, ws: WsConnectionLike) -> None:
        """A transport failure: forget the socket so next use reconnects."""
        if self._ws is ws:
            self._ws = None
        with contextlib.suppress(Exception):
            await ws.close()

    def _redact(self, message: str) -> str:
        """Every outgoing error string is scrubbed of key material."""
        if self._credentials is None:
            return message
        return redact_secret_material(message, [self._credentials.api_key])
