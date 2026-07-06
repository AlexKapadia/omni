"""Fan-out hub: engine events -> every connected WebSocket client.

Purpose: capture/transcript events are produced by ONE session but must
reach EVERY connected UI socket (main window, future overlay windows).
Connection handlers subscribe their send function; feature code calls
``broadcast`` without knowing who is listening.
Pipeline position: between event producers (``engine.stt``) and the
per-connection handlers in ``engine.websocket_connection_handler``.

Failure isolation invariant: one dead/slow subscriber must never block or
crash the others — per-subscriber errors are swallowed and logged, and the
failing subscriber is dropped (fail closed on the broken socket only).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from engine.protocol.websocket_envelope import PROTOCOL_VERSION, Envelope, EnvelopeKind

logger = logging.getLogger(__name__)

# A subscriber is "send one envelope to my client" — the handler's
# serialised send method.
SendFn = Callable[[Envelope], Awaitable[None]]


class EventBroadcastHub:
    """Register/unregister subscribers; broadcast events to all of them.

    Single-event-loop object: all methods are called from the engine's
    asyncio loop (handlers and pipelines share it), so a plain set is safe.
    """

    def __init__(self) -> None:
        self._subscribers: set[SendFn] = set()

    def subscribe(self, send: SendFn) -> Callable[[], None]:
        """Add a subscriber; returns its idempotent unsubscribe function."""
        self._subscribers.add(send)

        def unsubscribe() -> None:
            self._subscribers.discard(send)

        return unsubscribe

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def broadcast_event(self, name: str, payload: dict[str, Any]) -> None:
        """Wrap ``payload`` in a v1 event envelope and send to everyone.

        Iterates over a snapshot: a subscriber failing (client vanished
        mid-send) is unsubscribed and logged; remaining subscribers still
        receive the event (failure isolation).
        """
        envelope = Envelope(
            v=PROTOCOL_VERSION,
            kind=EnvelopeKind.EVENT,
            name=name,
            id=str(uuid.uuid4()),
            payload=payload,
        )
        for send in list(self._subscribers):
            try:
                await send(envelope)
            except Exception:
                self._subscribers.discard(send)
                logger.info("dropping broken event subscriber for %s", name, exc_info=True)
