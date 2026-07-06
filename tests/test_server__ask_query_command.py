"""WS ask surface: ``ask.query`` -> ``ask.answer`` (reconciliation wiring).

Drives the REAL app + connection handler with an injected fake ask gateway:
strict payload validation (deny by default), reply-name/reply-id
correlation on the pinned ``ask.answer`` shape, honest router refusals,
socket survival after a gateway crash, and the unwired refusal.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient, WebSocketTestSession

from engine.ask import AskAnswer, AskCitation, AskLatencyBreakdown
from engine.ask.ask_query_command_dispatcher import AskAnswerGateway, dispatch_ask_command
from engine.protocol import Envelope, EnvelopeKind
from engine.router.router_errors import KillSwitchEngagedError
from engine.server import create_app
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import receive_non_heartbeat_frame

ANSWER = AskAnswer(
    headline="Budget owner",
    answer_md="**Dana** owns the Q3 budget [1].",
    no_answer=False,
    citations=(
        AskCitation(
            n=1,
            note_path="Projects/budget.md",
            line_start=4,
            line_end=9,
            heading_path="Q3 > Owners",
            quote="Dana owns the Q3 budget.",
        ),
    ),
    latency=AskLatencyBreakdown(retrieval_ms=12, synthesis_ms=30),
)


class FakeAskGateway(AskAnswerGateway):
    """Scripted gateway: no DB, no router — just reply semantics."""

    def __init__(self) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"))
        self.queries: list[str] = []
        self.raises: Exception | None = None

    async def answer(self, query: str) -> AskAnswer:
        self.queries.append(query)
        if self.raises is not None:
            raise self.raises
        return ANSWER


class InertCaptureService(LiveCaptureService):
    """Handler dependency only — capture is exercised in its own suite."""

    def __init__(self, hub: Any) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


def make_app() -> tuple[Any, FakeAskGateway]:
    gateway = FakeAskGateway()
    app = create_app(
        capture_service_factory=InertCaptureService, ask_gateway_factory=lambda: gateway
    )
    return app, gateway


def command(name: str, payload: dict[str, Any], command_id: str | None = None) -> str:
    return json.dumps(
        {
            "v": 1,
            "kind": "command",
            "name": name,
            "id": command_id or str(uuid.uuid4()),
            "payload": payload,
        }
    )


def send_and_reply(ws: WebSocketTestSession, frame: str) -> dict[str, Any]:
    ws.send_text(frame)
    return receive_non_heartbeat_frame(ws)


def test_ask_query_replies_with_the_pinned_ask_answer_shape_and_id() -> None:
    app, gateway = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        reply = send_and_reply(ws, command("ask.query", {"query": "who owns the budget?"}, "q-1"))
    assert reply["kind"] == "reply"
    assert reply["name"] == "ask.answer"  # pinned reply name
    assert reply["id"] == "q-1"  # correlation id echoes the command
    assert reply["payload"] == {
        "headline": "Budget owner",
        "answer_md": "**Dana** owns the Q3 budget [1].",
        "no_answer": False,
        "citations": [
            {
                "n": 1,
                "note_path": "Projects/budget.md",
                "line_start": 4,
                "line_end": 9,
                "heading_path": "Q3 > Owners",
                "quote": "Dana owns the Q3 budget.",
            }
        ],
        # Latency arithmetic exact to the unit: 12 + 30 = 42, never a third
        # measurement (zero-numerical-errors rule).
        "latency": {"retrieval_ms": 12, "synthesis_ms": 30, "total_ms": 42},
    }
    assert gateway.queries == ["who owns the budget?"]


def test_hostile_ask_payloads_are_denied_before_the_gateway_runs() -> None:
    app, gateway = make_app()
    hostile: list[dict[str, Any]] = [
        {},  # query missing
        {"query": ""},  # empty
        {"query": "x" * 4001},  # just over the bound
        {"query": "ok", "mode": "fast"},  # unknown field
        {"query": 7},  # wrong type
        {"query": None},  # null
    ]
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for payload in hostile:
            reply = send_and_reply(ws, command("ask.query", payload, "bad"))
            assert reply["name"] == "error"
            assert reply["payload"]["code"] == "invalid_payload"
    assert gateway.queries == []  # nothing ever reached the gateway


def test_query_at_the_exact_length_bound_is_accepted() -> None:
    app, gateway = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        reply = send_and_reply(ws, command("ask.query", {"query": "x" * 4000}, "q-max"))
    assert reply["name"] == "ask.answer"
    assert gateway.queries == ["x" * 4000]  # carried verbatim


def test_router_refusal_maps_to_ask_error_and_the_socket_survives() -> None:
    app, gateway = make_app()
    gateway.raises = KillSwitchEngagedError()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        refused = send_and_reply(ws, command("ask.query", {"query": "anything"}, "q-2"))
        assert refused["name"] == "error" and refused["id"] == "q-2"
        assert refused["payload"]["code"] == "ask_error"
        # The socket must survive the refusal and keep answering.
        gateway.raises = None
        again = send_and_reply(ws, command("ask.query", {"query": "again"}, "q-3"))
    assert again["name"] == "ask.answer" and again["id"] == "q-3"


def test_unexpected_gateway_crash_is_an_error_reply_not_a_dead_socket() -> None:
    app, gateway = make_app()
    gateway.raises = RuntimeError("index exploded")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        reply = send_and_reply(ws, command("ask.query", {"query": "boom"}, "q-4"))
        assert reply["name"] == "error" and reply["payload"]["code"] == "ask_error"
        # ping still answers: the crash never killed the connection.
        pong = send_and_reply(ws, command("ping", {}, "p-1"))
    assert pong["name"] == "pong" and pong["id"] == "p-1"


async def test_dispatch_without_a_gateway_refuses_honestly() -> None:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    envelope = Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="ask.query", id="x-1", payload={"query": "hi"}
    )
    await dispatch_ask_command(envelope, None, send)
    assert len(sent) == 1
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "ask_error"
    assert "not available" in str(sent[0].payload["message"])
