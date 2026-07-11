"""Voice transport + command-surface edge branches (all faked, zero network).

Adversarial intent:
- Persistent Cartesia socket: the REAL websocket connect path (faked at
  ``websockets.connect``), backoff that re-checks the kill switch mid-wait, a
  connect that fails / is egress-blocked, empty-chunk rejection, a send that
  fails, a receive stall, cancel over a live / dead / absent socket, and
  key-scrubbed error strings.
- Command dispatcher: voice-unavailable refusal, the deny-by-default unknown
  command, and the ok/context_id happy path.
- Streaming TTS client: the real connect path and a cancel over a torn socket.
- TTS playback streamer: the already-finished cancel branch.
- Protocol builders: the affect-burst and error-payload boundaries.
"""

import asyncio
import json
from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from engine.ask.ask_answer_contracts import AskCitation
from engine.naomi.naomi_turn_protocol_names import (
    build_naomi_reply_payload,
    build_naomi_turn_error_payload,
)
from engine.protocol import EnvelopeKind
from engine.protocol.websocket_envelope import PROTOCOL_VERSION, Envelope
from engine.security import SecretApiKey
from engine.security.kill_switch import (
    KILL_SWITCH_ENV_VAR,
    set_kill_switch_runtime_override,
)
from engine.voice import persistent_cartesia_connection as pcc
from engine.voice.cartesia_credentials import CartesiaCredentials
from engine.voice.cartesia_message_framing import CartesiaAudioChunk, CartesiaDone
from engine.voice.cartesia_streaming_tts_client import CartesiaStreamingTtsClient
from engine.voice.naomi_voice_command_dispatcher import (
    VOICE_ERROR_CODE,
    dispatch_naomi_command,
)
from engine.voice.persistent_cartesia_connection import PersistentCartesiaConnection
from engine.voice.tts_playback_streamer import TtsPlaybackStreamer
from engine.voice.voice_errors import VoiceEgressBlockedError, VoiceProviderError

CREDS = CartesiaCredentials(
    api_key=SecretApiKey("sk-car-secret-KEYMATERIAL-9999"), voice_id="v-1"
)


@pytest.fixture(autouse=True)
def _clean_kill_switch(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(KILL_SWITCH_ENV_VAR, raising=False)
    set_kill_switch_runtime_override(None)
    yield
    set_kill_switch_runtime_override(None)


class FakeWs:
    """A controllable socket: records sends, feeds inbound frames, can fault."""

    def __init__(self, *, send_error: Exception | None = None) -> None:
        self.sent: list[str] = []
        self._inbox: asyncio.Queue[str | Exception] = asyncio.Queue()
        self.closed = False
        self._send_error = send_error

    async def send(self, data: str) -> None:
        if self._send_error is not None:
            raise self._send_error
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


def _chunk(context_id: str, data: str = "AAAA") -> str:
    return json.dumps({"type": "chunk", "context_id": context_id, "data": data})


def _done(context_id: str) -> str:
    return json.dumps({"type": "done", "context_id": context_id})


async def _drive_utterance(
    conn: PersistentCartesiaConnection, ctx: str, frames: Sequence[str], sockets: list[FakeWs]
) -> list[Any]:
    """Iterate one utterance, pushing its frames once the socket is live."""
    messages: list[Any] = []
    agen = conn.speak_utterance(["hi"], ctx, None)

    async def pusher() -> None:
        for _ in range(100):
            await asyncio.sleep(0)
            if sockets:
                break
        for frame in frames:
            sockets[0].push(frame)

    task = asyncio.create_task(pusher())
    async for message in agen:
        messages.append(message)
    await task
    return messages


# --- Persistent connection -------------------------------------------------


async def test_real_connect_path_uses_faked_websockets_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no injected factory, _connect imports websockets and dials it."""
    sockets: list[FakeWs] = []
    captured: dict[str, Any] = {}

    async def fake_connect(url: str, **kwargs: Any) -> FakeWs:
        captured["url"] = url
        captured["headers"] = kwargs.get("additional_headers")
        ws = FakeWs()
        sockets.append(ws)
        return ws

    import websockets

    monkeypatch.setattr(websockets, "connect", fake_connect)  # the network boundary
    conn = PersistentCartesiaConnection(credentials_loader=lambda: CREDS)

    messages = await _drive_utterance(conn, "ctx-1", [_chunk("ctx-1"), _done("ctx-1")], sockets)
    assert conn.is_connected
    assert "cartesia_version" in captured["url"]  # version query param present
    # The ONE place the key is revealed — straight into the connection header.
    assert captured["headers"] == {"X-API-Key": "sk-car-secret-KEYMATERIAL-9999"}
    assert any(isinstance(m, CartesiaAudioChunk) for m in messages)
    assert any(isinstance(m, CartesiaDone) for m in messages)
    await conn.close()


async def test_connect_failure_backs_off_then_rechecks_kill_switch() -> None:
    """A failed connect increments backoff; the switch is re-checked mid-wait."""
    attempts = [0]

    async def flaky_connect() -> FakeWs:
        attempts[0] += 1
        raise ConnectionError("dns exploded")

    async def engaging_sleep(_seconds: float) -> None:
        # The kill switch flips ON while we back off — the re-check must catch it.
        set_kill_switch_runtime_override(True)

    conn = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS, connect_factory=flaky_connect, sleep=engaging_sleep
    )

    # First use: connect fails → VoiceProviderError, redacted, failure counted.
    with pytest.raises(VoiceProviderError) as first:
        async for _ in conn.speak_utterance(["hi"], "ctx-a", None):
            pass
    assert "sk-car-secret" not in str(first.value)  # key scrubbed from the message
    assert attempts[0] == 1

    # Second use: failures>0 → backoff sleep engages the switch → egress blocked
    # BEFORE any further connect attempt (fail closed, re-checked after waiting).
    with pytest.raises(VoiceEgressBlockedError):
        async for _ in conn.speak_utterance(["hi"], "ctx-b", None):
            pass
    assert attempts[0] == 1  # no second connect was ever attempted


async def test_egress_blocked_from_connect_is_reraised_without_counting() -> None:
    """A VoiceEgressBlockedError from _connect propagates as-is (not wrapped)."""
    async def blocked_connect() -> FakeWs:
        raise VoiceEgressBlockedError()

    conn = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS, connect_factory=blocked_connect
    )
    with pytest.raises(VoiceEgressBlockedError):
        async for _ in conn.speak_utterance(["hi"], "ctx", None):
            pass


async def test_empty_chunks_are_rejected_before_any_egress() -> None:
    """speak_utterance with no chunks is a programming error, refused loudly."""
    conn = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS, connect_factory=lambda: FakeWs()  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(ValueError, match="at least one text chunk"):
        async for _ in conn.speak_utterance([], "ctx", None):
            pass


async def test_send_failure_marks_socket_dead_and_raises_redacted() -> None:
    """A send fault tears the socket and surfaces a redacted provider error."""
    sockets: list[FakeWs] = []

    async def factory() -> FakeWs:
        ws = FakeWs(send_error=ConnectionResetError("socket write failed"))
        sockets.append(ws)
        return ws

    conn = PersistentCartesiaConnection(credentials_loader=lambda: CREDS, connect_factory=factory)
    with pytest.raises(VoiceProviderError, match="cartesia send failed"):
        async for _ in conn.speak_utterance(["hi"], "ctx", None):
            pass
    assert not conn.is_connected  # torn socket forgotten → next use reconnects
    assert sockets[0].closed is True
    await conn.close()


async def test_receive_stall_times_out_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A black-holed stream (no frame within budget) fails, never hangs a turn."""
    monkeypatch.setattr(pcc, "_RECEIVE_TIMEOUT_SECONDS", 0.02)  # shrink the budget
    sockets: list[FakeWs] = []

    async def factory() -> FakeWs:
        ws = FakeWs()  # never pushes a frame → the receive stalls
        sockets.append(ws)
        return ws

    conn = PersistentCartesiaConnection(credentials_loader=lambda: CREDS, connect_factory=factory)
    with pytest.raises(VoiceProviderError, match="stalled"):
        async for _ in conn.speak_utterance(["hi"], "ctx", None):
            pass
    assert not conn.is_connected
    await conn.close()


async def test_undecodable_inbound_frame_is_dropped_not_surfaced() -> None:
    """A garbage frame parses to None and is skipped; the stream keeps flowing."""
    sockets: list[FakeWs] = []
    conn = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS,
        connect_factory=_socket_factory(sockets),
    )
    messages = await _drive_utterance(
        conn, "ctx-real", ["}{ not json", _chunk("ctx-real"), _done("ctx-real")], sockets
    )
    assert any(isinstance(m, CartesiaAudioChunk) for m in messages)  # valid frame survived
    assert any(isinstance(m, CartesiaDone) for m in messages)
    await conn.close()


async def test_cancel_over_absent_live_and_dead_sockets() -> None:
    """cancel: False with no socket, True on a live one, False when send faults."""
    # No socket yet: cancel is a no-op returning False (nothing to silence).
    conn = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS, connect_factory=lambda: FakeWs()  # type: ignore[arg-type,return-value]
    )
    assert await conn.cancel("ctx") is False

    # Live socket: cancel sends the barge-in frame and reports success.
    live_sockets: list[FakeWs] = []
    live = PersistentCartesiaConnection(
        credentials_loader=lambda: CREDS, connect_factory=_socket_factory(live_sockets)
    )
    await _drive_utterance(live, "ctx-x", [_chunk("ctx-x"), _done("ctx-x")], live_sockets)
    connected_before = live.is_connected
    assert connected_before is True
    cancel_ok = await live.cancel("ctx-x")
    assert cancel_ok is True
    assert any("cancel" in frame for frame in live_sockets[0].sent)

    # Faulting send on cancel: the socket is torn and cancel reports False.
    live_sockets[0]._send_error = ConnectionResetError("gone")
    cancel_failed = await live.cancel("ctx-x")
    assert cancel_failed is False
    connected_after = live.is_connected
    assert connected_after is False
    await live.close()


async def test_voice_id_change_forces_reconnect_and_uses_new_voice() -> None:
    """Clearing/changing CARTESIA_VOICE_ID must not keep speaking with a stale warm voice."""
    sockets: list[FakeWs] = []
    current = CartesiaCredentials(
        api_key=SecretApiKey("sk-car-secret-KEYMATERIAL-9999"), voice_id="voice-old"
    )

    def loader() -> CartesiaCredentials:
        return current

    conn = PersistentCartesiaConnection(
        credentials_loader=loader, connect_factory=_socket_factory(sockets)
    )
    await _drive_utterance(
        conn, "ctx-1", [_chunk("ctx-1"), _done("ctx-1")], sockets
    )
    assert len(sockets) == 1
    assert "voice-old" in sockets[0].sent[0]

    current = CartesiaCredentials(
        api_key=SecretApiKey("sk-car-secret-KEYMATERIAL-9999"), voice_id="voice-new"
    )

    messages: list[Any] = []
    agen = conn.speak_utterance(["hi"], "ctx-2", None)

    async def pusher() -> None:
        for _ in range(100):
            await asyncio.sleep(0)
            if len(sockets) >= 2:
                break
        for frame in [_chunk("ctx-2"), _done("ctx-2")]:
            sockets[-1].push(frame)

    task = asyncio.create_task(pusher())
    async for message in agen:
        messages.append(message)
    await task
    assert len(sockets) == 2
    assert "voice-new" in sockets[1].sent[0]
    assert any(isinstance(m, CartesiaDone) for m in messages)
    await conn.close()


def _socket_factory(sockets: list[FakeWs]) -> Any:
    async def factory() -> FakeWs:
        ws = FakeWs()
        sockets.append(ws)
        return ws

    return factory


# --- Command dispatcher ----------------------------------------------------


class FakeStreamer:
    def __init__(self, say_result: str = "ctx-say") -> None:
        self.say_result = say_result
        self.said: list[tuple[str, object]] = []

    async def say(self, text: str, affect: object) -> str:
        self.said.append((text, affect))
        return self.say_result

    async def cancel(self) -> str | None:
        return None


def _command(name: str, payload: dict[str, Any], cid: str = "c1") -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.COMMAND, name=name, id=cid, payload=payload
    )


async def _dispatch(command: Envelope, streamer: object) -> list[Envelope]:
    replies: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        replies.append(envelope)

    await dispatch_naomi_command(command, streamer, send)  # type: ignore[arg-type]
    return replies


async def test_dispatch_refuses_when_voice_is_unavailable() -> None:
    """No streamer wired → an honest voice_error, never a silent drop."""
    replies = await _dispatch(_command("naomi.say", {"text": "hi"}), None)
    assert len(replies) == 1
    assert replies[0].name == "error"
    assert replies[0].payload["code"] == VOICE_ERROR_CODE
    assert "not available" in str(replies[0].payload["message"])


async def test_dispatch_unknown_command_denies_by_default() -> None:
    """A routing bug reaching an unknown name still gets a deny-by-default reply."""
    replies = await _dispatch(_command("naomi.bogus", {}), FakeStreamer())
    assert replies[0].name == "error"
    assert replies[0].payload["code"] == "unknown_command"


async def test_dispatch_say_happy_path_returns_context_id() -> None:
    """A valid naomi.say replies ok with the new utterance's context_id."""
    streamer = FakeStreamer(say_result="ctx-777")
    replies = await _dispatch(_command("naomi.say", {"text": "Hello"}, "say-1"), streamer)
    assert replies[0].name == "ok"
    assert replies[0].id == "say-1"  # correlation contract
    assert replies[0].payload == {"context_id": "ctx-777"}
    assert streamer.said == [("Hello", None)]


# --- Streaming TTS client --------------------------------------------------


class ClientFakeWs:
    """A one-shot client socket: records sends, replays scripted inbound frames."""

    def __init__(self, inbound: Sequence[str], *, send_error: Exception | None = None) -> None:
        self.sent: list[str] = []
        self._inbound = list(inbound)
        self.closed = False
        self._send_error = send_error

    async def send(self, data: str) -> None:
        if self._send_error is not None:
            raise self._send_error
        self.sent.append(data)

    async def recv(self) -> str:
        return self._inbound.pop(0)

    async def close(self) -> None:
        self.closed = True


async def test_client_real_connect_path_uses_faked_websockets_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-shot client's real _connect dials the faked websockets.connect."""
    captured: dict[str, Any] = {}

    async def fake_connect(url: str, **kwargs: Any) -> ClientFakeWs:
        captured["headers"] = kwargs.get("additional_headers")
        return ClientFakeWs([_chunk("ctx-1"), _done("ctx-1")])

    import websockets

    monkeypatch.setattr(websockets, "connect", fake_connect)
    client = CartesiaStreamingTtsClient(CREDS)

    messages = [m async for m in client.stream_utterance("hi", "ctx-1", None)]
    assert captured["headers"] == {"X-API-Key": "sk-car-secret-KEYMATERIAL-9999"}
    assert any(isinstance(m, CartesiaAudioChunk) for m in messages)
    assert any(isinstance(m, CartesiaDone) for m in messages)


async def test_client_cancel_over_torn_socket_returns_false_never_raises() -> None:
    """A cancel whose send faults means generation is already dead → False."""
    client = CartesiaStreamingTtsClient(CREDS)
    torn = ClientFakeWs([], send_error=ConnectionResetError("dead"))
    client._active_ws = torn
    client._active_context_id = "ctx-1"
    assert await client.cancel("ctx-1") is False  # honest, no exception escapes


# --- TTS playback streamer -------------------------------------------------


async def test_streamer_cancel_returns_none_when_task_already_finished() -> None:
    """Defensive branch: a done-but-tracked task yields no duplicate done."""
    from engine.protocol import EventBroadcastHub

    streamer = TtsPlaybackStreamer(EventBroadcastHub(), client_factory=lambda: _unused_client())

    async def _done_task() -> None:
        return None

    task: asyncio.Task[None] = asyncio.create_task(_done_task())
    await task
    streamer._active_task = task
    streamer._active_context_id = "ctx-finished"
    streamer._active_client = None
    assert await streamer.cancel() is None  # relay already reported its own done


def _unused_client() -> Any:  # pragma: no cover - factory never invoked in the test
    raise AssertionError("client factory must not run")


# --- Protocol builders -----------------------------------------------------


def test_reply_payload_carries_burst_only_when_present() -> None:
    """The affect burst rides ONLY when set; action_card_id only when prepared."""
    citation = AskCitation(
        n=1, note_path="N.md", line_start=1, line_end=2, heading_path="H", quote="q"
    )
    with_burst = build_naomi_reply_payload(
        "t1", "spoken", (0.6, 0.5, "laugh"), (citation,), no_answer=False, action_card_id=9
    )
    assert with_burst["affect"] == {"v": 0.6, "a": 0.5, "burst": "laugh"}
    assert with_burst["action_card_id"] == 9
    citations = with_burst["citations"]
    assert isinstance(citations, list)
    first_citation = citations[0]
    assert isinstance(first_citation, dict)
    assert first_citation["note_path"] == "N.md"

    without = build_naomi_reply_payload(
        "t2", "spoken", (0.6, 0.5, None), (), no_answer=True, action_card_id=None
    )
    without_affect = without["affect"]
    assert isinstance(without_affect, dict)
    assert "burst" not in without_affect  # burst absent → key omitted
    assert "action_card_id" not in without  # no card prepared → key omitted


def test_turn_error_payload_bounds_message_and_optional_turn_id() -> None:
    """Reflected error text is capped at 300 chars; turn_id rides only when set."""
    long_message = "x" * 500
    bounded = build_naomi_turn_error_payload(long_message, "turn-9")
    assert bounded["message"] == "x" * 300  # exact bound: 500 → 300
    assert bounded["turn_id"] == "turn-9"

    anonymous = build_naomi_turn_error_payload("short")
    assert anonymous == {"message": "short"}  # no turn_id key when None
