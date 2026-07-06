"""Barge-in wire semantics: cancel frames, one-mouth discipline (a new say
cancels the old utterance first), idempotent cancels, and honest
naomi.audio.done(cancelled) broadcasts.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from engine.protocol import Envelope, EventBroadcastHub
from engine.security import SecretApiKey
from engine.voice.cartesia_credentials import CartesiaCredentials
from engine.voice.cartesia_message_framing import CartesiaAudioChunk, CartesiaMessage
from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer

CREDS = CartesiaCredentials(
    api_key=SecretApiKey("sk-car-test-0123456789abcdef"), voice_id="voice-abc"
)


class HangingWs:
    """Yields one chunk then hangs — an utterance mid-flight, cancellable."""

    def __init__(self, context_id: str) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._context_id = context_id
        self._first = True

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        if self._first:
            self._first = False
            return json.dumps({"type": "chunk", "context_id": self._context_id, "data": "QQ=="})
        await asyncio.Event().wait()  # hang until the task is cancelled
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed = True


class OneChunkClient(CartesiaStreamingTtsClient):
    """Streamer-level fake: one chunk then hang; records cancel calls."""

    def __init__(self) -> None:
        super().__init__(CREDS, connect_factory=None)
        self.cancelled_contexts: list[str] = []
        self.started = asyncio.Event()

    async def stream_utterance(
        self, text: str, context_id: str, affect: tuple[float, float] | None
    ) -> AsyncIterator[CartesiaMessage]:
        yield CartesiaAudioChunk(context_id=context_id, data_b64="QQ==")
        self.started.set()
        await asyncio.Event().wait()  # speak forever until cancelled

    async def cancel(self, context_id: str) -> bool:
        self.cancelled_contexts.append(context_id)
        return True


def collect_hub() -> tuple[EventBroadcastHub, list[Envelope]]:
    hub = EventBroadcastHub()
    seen: list[Envelope] = []

    async def collector(envelope: Envelope) -> None:
        seen.append(envelope)

    hub.subscribe(collector)
    return hub, seen


# ---------------------------------------------------------------------------
# Client-level: the exact cancel frame, scoped to the active context
# ---------------------------------------------------------------------------


async def test_client_cancel_sends_the_exact_cancel_frame_mid_stream() -> None:
    ws = HangingWs("ctx-live")

    async def connect() -> HangingWs:
        return ws

    client = CartesiaStreamingTtsClient(CREDS, connect_factory=connect)

    async def consume() -> None:
        async for _ in client.stream_utterance("Hello", "ctx-live", None):
            pass

    task = asyncio.create_task(consume())
    for _ in range(100):  # wait until the stream is mid-flight
        await asyncio.sleep(0)
    assert await client.cancel("ctx-live") is True
    assert json.loads(ws.sent[-1]) == {"context_id": "ctx-live", "cancel": True}
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_client_cancel_for_a_foreign_or_finished_context_is_a_noop() -> None:
    client = CartesiaStreamingTtsClient(CREDS, connect_factory=None)
    assert await client.cancel("never-started") is False  # nothing sent, no error


# ---------------------------------------------------------------------------
# Streamer-level: one mouth, honest done(cancelled) events
# ---------------------------------------------------------------------------


async def test_cancel_stops_the_utterance_and_broadcasts_cancelled() -> None:
    hub, seen = collect_hub()
    client = OneChunkClient()
    streamer = TtsPlaybackStreamer(hub, client_factory=lambda: client)
    context_id = await streamer.say("Hello there", None)
    await asyncio.wait_for(client.started.wait(), timeout=2)
    cancelled = await streamer.cancel()
    assert cancelled == context_id
    assert client.cancelled_contexts == [context_id]  # Cartesia told to stop
    done = [e for e in seen if e.name == "naomi.audio.done"]
    assert len(done) == 1
    assert done[0].payload == {"context_id": context_id, "reason": "cancelled"}
    assert streamer.active_context_id is None


async def test_cancel_with_nothing_speaking_is_idempotent() -> None:
    hub, seen = collect_hub()
    streamer = TtsPlaybackStreamer(hub, client_factory=OneChunkClient)
    assert await streamer.cancel() is None
    assert await streamer.cancel() is None
    assert seen == []  # no phantom done events


async def test_new_say_barges_in_on_the_previous_utterance_first() -> None:
    hub, seen = collect_hub()
    clients: list[OneChunkClient] = []

    def factory() -> OneChunkClient:
        client = OneChunkClient()
        clients.append(client)
        return client

    streamer = TtsPlaybackStreamer(hub, client_factory=factory)
    first_context = await streamer.say("First sentence", None)
    await asyncio.wait_for(clients[0].started.wait(), timeout=2)
    second_context = await streamer.say("Second sentence", None)
    assert second_context != first_context
    # The first utterance got a provider cancel AND a cancelled done event.
    assert clients[0].cancelled_contexts == [first_context]
    done = [e for e in seen if e.name == "naomi.audio.done"]
    assert [d.payload["context_id"] for d in done] == [first_context]
    assert done[0].payload["reason"] == "cancelled"
    # The second utterance is now the active mouth.
    assert streamer.active_context_id == second_context
    await streamer.shutdown()


async def test_shutdown_never_orphans_a_speaking_task() -> None:
    hub, _ = collect_hub()
    client = OneChunkClient()
    streamer = TtsPlaybackStreamer(hub, client_factory=lambda: client)
    await streamer.say("Long speech", None)
    await asyncio.wait_for(client.started.wait(), timeout=2)
    await streamer.shutdown()
    assert streamer.active_context_id is None
    # All tasks done: nothing left running on the loop from the streamer.
    await asyncio.sleep(0)
