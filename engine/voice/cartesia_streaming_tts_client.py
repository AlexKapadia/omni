"""Cartesia streaming TTS client: one WebSocket utterance at a time.

Purpose: opens the Cartesia TTS WebSocket (wss://api.cartesia.ai/tts/websocket,
pinned model ``sonic-3.5-2026-05-04``, pcm_f32le @ 24kHz, word timestamps on),
streams the generation messages back to the caller, and carries the cancel
(barge-in) primitive. Framing lives in ``cartesia_message_framing``; this
module owns connection lifecycle and error redaction.
Pipeline position: constructed by ``tts_playback_streamer``; the ONLY module
that talks to Cartesia.

Security invariants (claude.md §5.6 project bindings):
- Kill switch checked BEFORE any connection is attempted — engaged means
  no egress, full stop (fail closed).
- The API key is revealed ONLY into the connection header; every error
  string is scrubbed with redact_secret_material before it propagates.
- Inbound provider frames are untrusted: parsed fail-closed; frames for
  other context_ids are dropped, never surfaced.
"""

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from engine.security import kill_switch_engaged, redact_secret_material
from engine.voice.cartesia_credentials import CartesiaCredentials
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
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

# Bound the provider handshake so a black-holed connect cannot hang a turn.
_CONNECT_TIMEOUT_SECONDS = 10.0


class WsConnectionLike(Protocol):
    """The minimal WebSocket surface the client needs — tests inject fakes."""

    async def send(self, data: str) -> None: ...  # pragma: no cover - protocol
    async def recv(self) -> str | bytes: ...  # pragma: no cover - protocol
    async def close(self) -> None: ...  # pragma: no cover - protocol


ConnectFactory = Callable[[], Awaitable[WsConnectionLike]]


class CartesiaStreamingTtsClient:
    """Streams one utterance per call; cancel() is the barge-in wire."""

    def __init__(
        self,
        credentials: CartesiaCredentials,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        self._credentials = credentials
        self._connect_factory = connect_factory
        self._active_ws: WsConnectionLike | None = None
        self._active_context_id: str | None = None

    async def _connect(self) -> WsConnectionLike:
        if self._connect_factory is not None:
            return await self._connect_factory()
        # Lazy import: the engine (and hermetic tests) load without opening
        # any network machinery.
        import websockets

        url = f"{CARTESIA_WSS_URL}?cartesia_version={CARTESIA_API_VERSION}"
        connection = await websockets.connect(
            url,
            # The ONE place the key is revealed — straight into the header.
            additional_headers={"X-API-Key": self._credentials.api_key.reveal()},
            open_timeout=_CONNECT_TIMEOUT_SECONDS,
        )
        return connection

    async def stream_utterance(
        self,
        text: str,
        context_id: str,
        affect: tuple[float, float] | None,
    ) -> AsyncIterator[CartesiaMessage]:
        """Send one generation request and yield its messages until done.

        Raises VoiceEgressBlockedError (kill switch) BEFORE connecting, and
        VoiceProviderError (redacted) on any transport/provider failure.
        """
        # Kill-switch gate FIRST: engaged means the connection is never
        # even attempted (fail closed on egress — §5.6 binding).
        if kill_switch_engaged():
            raise VoiceEgressBlockedError()
        try:
            ws = await self._connect()
        except Exception as exc:
            # `from None`: the raw exception may echo request headers (the
            # key). Redact and drop the chain so no log can resurrect it.
            raise VoiceProviderError(self._redact(f"cartesia connect failed: {exc}")) from None
        self._active_ws = ws
        self._active_context_id = context_id
        try:
            request = build_generation_request(text, context_id, self._credentials.voice_id, affect)
            await ws.send(request)
            while True:
                raw = await ws.recv()
                message = parse_cartesia_message(raw)
                if message is None or message.context_id != context_id:
                    continue  # untrusted/foreign frame: drop, never crash
                yield message
                if isinstance(message, CartesiaDone | CartesiaErrorMessage):
                    return
        except Exception as exc:
            raise VoiceProviderError(self._redact(f"cartesia stream failed: {exc}")) from None
        finally:
            self._active_ws = None
            self._active_context_id = None
            with contextlib.suppress(Exception):
                await ws.close()

    async def cancel(self, context_id: str) -> bool:
        """Send the cancel frame for the active context (barge-in).

        Returns False when there is nothing matching to cancel — cancelling
        a finished/foreign utterance is a no-op, not an error.
        """
        ws = self._active_ws
        if ws is None or self._active_context_id != context_id:
            return False
        try:
            await ws.send(build_cancel_request(context_id))
            return True
        except Exception:
            # A torn socket means generation is already dead — the goal
            # (silence) is achieved; report honestly without raising.
            return False

    def _redact(self, message: str) -> str:
        """Every outgoing error string is scrubbed of key material."""
        return redact_secret_material(message, [self._credentials.api_key])
