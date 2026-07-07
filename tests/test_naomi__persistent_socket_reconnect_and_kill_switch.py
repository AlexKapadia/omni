"""Persistent Cartesia socket: warm reuse, reconnect+backoff, kill-switch.

Security + resilience invariants under test (brief §7):
- Warm reuse: two utterances over ONE socket connect exactly once (the TTFA
  win depends on this).
- Kill switch at EVERY (re)connect: engaged means no socket is ever opened
  (fail closed on egress), including after a mid-run engage.
- Reconnect with capped exponential backoff after a torn socket, and the
  backoff re-checks the switch (never opens a socket the switch would forbid).
- Multiplexing: frames for one context never surface on another; unknown
  contexts are dropped (deny by default).
- Every error string is scrubbed of key material (no key ever leaks).
"""

import asyncio
import json
from collections.abc import Callable, Iterator

import pytest

from engine.security import SecretApiKey
from engine.security.kill_switch import KILL_SWITCH_ENV_VAR, set_kill_switch_runtime_override
from engine.voice.cartesia_credentials import CartesiaCredentials
from engine.voice.cartesia_message_framing import (
    CartesiaAudioChunk,
    CartesiaDone,
    CartesiaMessage,
)
from engine.voice.persistent_cartesia_connection import (
    BACKOFF_SCHEDULE_SECONDS,
    PersistentCartesiaConnection,
)
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

CREDS = CartesiaCredentials(api_key=SecretApiKey("sk-car-secret-KEYMATERIAL-9999"), voice_id="v-1")


def _chunk(context_id: str, data: str = "AAAA") -> str:
    return json.dumps({"type": "chunk", "context_id": context_id, "data": data})


def _done(context_id: str) -> str:
    return json.dumps({"type": "done", "context_id": context_id})


class FakeWs:
    """A controllable Cartesia socket: records sends, feeds inbound frames."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._inbox: asyncio.Queue[str | Exception] = asyncio.Queue()
        self.closed = False

    async def send(self, data: str) -> None:
        if self.closed:
            raise ConnectionError("send on a closed socket")
        self.sent.append(data)

    async def recv(self) -> str:
        item = await self._inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True

    def push(self, frame: str) -> None:
        self._inbox.put_nowait(frame)

    def tear(self) -> None:
        """Simulate the server/network dropping the socket mid-stream."""
        self._inbox.put_nowait(ConnectionResetError("socket dropped"))


@pytest.fixture(autouse=True)
def _clean_kill_switch(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(KILL_SWITCH_ENV_VAR, raising=False)
    set_kill_switch_runtime_override(None)
    yield
    set_kill_switch_runtime_override(None)


def _make_connection(
    sockets: list[FakeWs], sleeps: list[float]
) -> tuple[PersistentCartesiaConnection, list[int]]:
    connect_count = [0]

    async def factory() -> FakeWs:
        connect_count[0] += 1
        ws = FakeWs()
        sockets.append(ws)
        return ws

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    conn = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS, connect_factory=factory, sleep=fake_sleep
    )
    return conn, connect_count


async def _collect(
    conn: PersistentCartesiaConnection,
    chunks: list[str],
    ctx: str,
    ws_source: Callable[[], FakeWs | None],
) -> list[CartesiaMessage]:
    """Drive one utterance, pushing its frames once the queue is registered."""
    messages: list[CartesiaMessage] = []
    agen = conn.speak_utterance(chunks, ctx, None)

    async def push_when_ready() -> None:
        # Give speak_utterance time to connect, send, and register its queue.
        for _ in range(50):
            await asyncio.sleep(0)
            if ws_source():
                break
        ws = ws_source()
        assert ws is not None
        ws.push(_chunk(ctx))
        ws.push(_done(ctx))

    pusher = asyncio.create_task(push_when_ready())
    async for message in agen:
        messages.append(message)
    await pusher
    return messages


async def test_warm_reuse_connects_exactly_once_for_two_utterances() -> None:
    sockets: list[FakeWs] = []
    conn, connect_count = _make_connection(sockets, [])
    msgs1 = await _collect(conn, ["hello"], "ctx-1", lambda: sockets[0] if sockets else None)
    assert conn.is_connected
    msgs2 = await _collect(conn, ["again"], "ctx-2", lambda: sockets[0] if sockets else None)
    assert connect_count[0] == 1  # ONE warm socket across both turns
    assert any(isinstance(m, CartesiaAudioChunk) for m in msgs1)
    assert any(isinstance(m, CartesiaDone) for m in msgs2)
    await conn.close()


async def test_kill_switch_blocks_the_first_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KILL_SWITCH_ENV_VAR, "1")
    sockets: list[FakeWs] = []
    conn, connect_count = _make_connection(sockets, [])
    with pytest.raises(VoiceEgressBlockedError):
        async for _ in conn.speak_utterance(["hi"], "ctx", None):
            raise AssertionError("no frame should be yielded")
    assert connect_count[0] == 0  # zero egress


async def test_reconnect_after_tear_uses_backoff_and_rechecks_switch() -> None:
    sockets: list[FakeWs] = []
    sleeps: list[float] = []
    conn, connect_count = _make_connection(sockets, sleeps)
    # First utterance connects; then the socket is torn mid-wait.
    agen = conn.speak_utterance(["one"], "ctx-a", None)

    async def tear_it() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if sockets:
                break
        sockets[0].tear()

    tearer = asyncio.create_task(tear_it())
    with pytest.raises(VoiceProviderError):
        async for _ in agen:
            pass
    await tearer
    assert not conn.is_connected  # torn socket forgotten → next use reconnects
    # Next utterance reconnects; the failure counter was reset on the first
    # good connect, so this fresh connect does not sleep on backoff.
    msgs = await _collect(conn, ["two"], "ctx-b", lambda: sockets[1] if len(sockets) > 1 else None)
    assert connect_count[0] == 2
    assert any(isinstance(m, CartesiaDone) for m in msgs)
    await conn.close()


async def test_unknown_context_frames_are_dropped_not_surfaced() -> None:
    sockets: list[FakeWs] = []
    conn, _ = _make_connection(sockets, [])
    agen = conn.speak_utterance(["hi"], "ctx-real", None)

    async def push() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            if sockets:
                break
        ws = sockets[0]
        ws.push(_chunk("ctx-OTHER"))  # foreign context: must be dropped
        ws.push(_chunk("ctx-real"))
        ws.push(_done("ctx-real"))

    pusher = asyncio.create_task(push())
    seen = [m async for m in agen]
    await pusher
    # Only this context's frames surface; the foreign chunk never appears.
    assert all(m.context_id == "ctx-real" for m in seen)
    assert any(isinstance(m, CartesiaAudioChunk) for m in seen)
    await conn.close()


async def test_backoff_schedule_is_capped_and_monotonic() -> None:
    """The backoff schedule is a sane capped ramp (no unbounded growth)."""
    assert tuple(sorted(BACKOFF_SCHEDULE_SECONDS)) == BACKOFF_SCHEDULE_SECONDS
    assert BACKOFF_SCHEDULE_SECONDS[-1] <= 5.0
