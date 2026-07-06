"""WS approval-card surface: ``cards.list`` / ``card.approve`` / ``card.dismiss``
/ ``card.retry`` wiring, pinned to ``engine/agents/approval_protocol_names.py``.

Drives the REAL app + connection handler + gateway + repositories + executor
against a tmp_path SQLite database migrated with the REAL migration files
and a tmp_path synthetic vault. Google is a fake that fails closed with
"Google account not connected" — this box's real state. Asserts the
``card.updated`` broadcast on EVERY status change (approved, executing,
executed/failed, dismissed, retry clone) and every refusal path
(validation, unknown id, illegal transitions) as typed errors.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite
from starlette.testclient import TestClient, WebSocketTestSession

from engine.approval_cards_gateway import ApprovalCardsGateway
from engine.google.google_auth_errors import GoogleNotConnectedError
from engine.google.google_session import GoogleSession
from engine.protocol import EventBroadcastHub
from engine.router.fallback_executor import ProviderRouter
from engine.server import create_app
from engine.storage import apply_migrations
from engine.stt.live_capture_service import LiveCaptureService
from tests.conftest import REPO_ROOT, receive_frame

MIGRATIONS = REPO_ROOT / "migrations"
TS = "2026-07-06T12:00:00+00:00"

WRITE_NOTE_PAYLOAD = '{"title": "Retro follow-ups", "body_markdown": "- send the deck"}'
EVENT_PAYLOAD = (
    '{"title": "Sync with Priya", "when_hint": null, "start_iso": "2026-07-08T13:00:00+00:00",'
    ' "end_iso": "2026-07-08T14:00:00+00:00", "attendees": [], "description": null}'
)


class NotConnectedGoogleSession(GoogleSession):
    """This box's real state: no DPAPI tokens — every call refuses."""

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        raise GoogleNotConnectedError


class InertCaptureService(LiveCaptureService):
    """Handler dependency only — capture is exercised in its own suite."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        super().__init__(db_path=Path("unused.db"), migrations_dir=Path("unused"), hub=hub)


def make_app(tmp_db: Path, tmp_vault: Path) -> Any:
    def gateway_factory(hub: EventBroadcastHub) -> ApprovalCardsGateway:
        return ApprovalCardsGateway(
            hub=hub,
            db_path=tmp_db,
            migrations_dir=MIGRATIONS,
            google_session_factory=NotConnectedGoogleSession,
            # Keyless router: never consulted on deterministic mappings; an
            # (unused) LLM fallback would refuse, not call out.
            router_factory=lambda recorder: ProviderRouter({}, recorder),
            vault_root_resolver=lambda: tmp_vault,
        )

    return create_app(
        capture_service_factory=InertCaptureService, approval_gateway_factory=gateway_factory
    )


async def seed_pending_card(
    tmp_db: Path, *, card_type: str = "write_note", payload_json: str = WRITE_NOTE_PAYLOAD
) -> int:
    """One pending dictation-sourced card in a freshly migrated database."""
    await apply_migrations(tmp_db, MIGRATIONS)
    connection = await aiosqlite.connect(tmp_db)
    try:
        cursor = await connection.execute(
            "INSERT INTO approval_cards"
            " (meeting_id, source, source_row_id, card_type, payload_json, status, created_at)"
            " VALUES (NULL, 'dictation', 1, ?, ?, 'pending', ?)",
            (card_type, payload_json, TS),
        )
        card_id = int(cursor.lastrowid or 0)
        await connection.commit()
        return card_id
    finally:
        await connection.close()


async def seed_failed_card(tmp_db: Path, *, card_type: str, payload_json: str) -> int:
    """Walk a card to 'failed' through the ONLY legal path (0008 triggers)."""
    card_id = await seed_pending_card(tmp_db, card_type=card_type, payload_json=payload_json)
    connection = await aiosqlite.connect(tmp_db)
    try:
        for sql in (
            "UPDATE approval_cards SET status='approved', decided_at=? WHERE id=?",
            "UPDATE approval_cards SET status='executing' WHERE id=?",
            "UPDATE approval_cards SET status='failed', executed_at=?, error='boom' WHERE id=?",
        ):
            params = (TS, card_id) if sql.count("?") == 2 else (card_id,)
            await connection.execute(sql, params)
        await connection.commit()
        return card_id
    finally:
        await connection.close()


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


def next_relevant(ws: WebSocketTestSession, limit: int = 60) -> dict[str, Any]:
    """The next reply or card.updated event, skipping heartbeats."""
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame.get("name") == "engine.heartbeat":
            continue
        return frame
    raise AssertionError(f"no relevant frame within {limit} frames")


def collect_statuses_until(
    ws: WebSocketTestSession, final_statuses: set[str], limit: int = 60
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(card.updated card payloads in order, the command reply)."""
    cards: list[dict[str, Any]] = []
    reply: dict[str, Any] | None = None
    terminal_seen = False
    for _ in range(limit):
        frame = receive_frame(ws)
        if frame.get("name") == "engine.heartbeat":
            continue
        if frame["kind"] == "reply":
            reply = frame
        elif frame["kind"] == "event" and frame["name"] == "card.updated":
            cards.append(frame["payload"]["card"])
            terminal_seen = terminal_seen or frame["payload"]["card"]["status"] in final_statuses
        if terminal_seen and reply is not None:
            return cards, reply
    raise AssertionError(f"no terminal card.updated + reply within {limit} frames: {cards}")


async def db_card(tmp_db: Path, card_id: int) -> tuple[str, str]:
    connection = await aiosqlite.connect(tmp_db)
    try:
        cursor = await connection.execute(
            "SELECT status, payload_json FROM approval_cards WHERE id = ?", (card_id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        return str(row[0]), str(row[1])
    finally:
        await connection.close()


# ------------------------------------------------------------------ cards.list
def test_cards_list_empty_database_replies_ok_with_no_cards(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("cards.list", {}, "l-1"))
        reply = next_relevant(ws)
    assert reply["name"] == "ok" and reply["id"] == "l-1"
    assert reply["payload"] == {"cards": []}


def test_cards_list_returns_pinned_card_shape_newest_first(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    first = asyncio.run(seed_pending_card(tmp_db_path))
    second = asyncio.run(
        seed_pending_card(
            tmp_db_path,
            card_type="upsert_contact",
            payload_json='{"name": "Priya Patel", "email": "priya@example.com"}',
        )
    )
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("cards.list", {}, "l-2"))
        reply = next_relevant(ws)
    cards = reply["payload"]["cards"]
    assert [card["id"] for card in cards] == [second, first]  # newest first
    top = cards[0]
    # The full pinned shape the UI parses fail-closed.
    assert set(top) == {
        "id", "meeting_id", "source", "card_type", "status", "payload", "preview_lines",
        "created_at", "decided_at", "executed_at", "error", "result_summary",
    }
    assert top["status"] == "pending" and top["source"] == "dictation"
    assert top["payload"]["name"] == "Priya Patel"
    assert any("Priya Patel" in line for line in top["preview_lines"])


# ---------------------------------------------------------------- card.approve
def test_approve_write_note_walks_approved_executing_executed_with_events(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    card_id = asyncio.run(seed_pending_card(tmp_db_path))
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.approve", {"id": card_id}, "a-1"))
        cards, reply = collect_statuses_until(ws, {"executed", "failed"})
    assert reply["name"] == "ok" and reply["id"] == "a-1" and reply["payload"] == {}
    statuses = [card["status"] for card in cards if card["id"] == card_id]
    # EVERY status change broadcast, in order (pinned spec).
    assert statuses == ["approved", "executing", "executed"]
    assert cards[-1]["result_summary"] is not None
    # The vault-write tool really ran: the note exists in the tmp vault.
    inbox_notes = list((tmp_path / "Inbox").glob("*.md"))
    assert len(inbox_notes) == 1
    assert "- send the deck" in inbox_notes[0].read_text(encoding="utf-8")
    assert asyncio.run(db_card(tmp_db_path, card_id))[0] == "executed"


def test_approve_google_card_fails_closed_google_not_connected(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    card_id = asyncio.run(
        seed_pending_card(tmp_db_path, card_type="create_event", payload_json=EVENT_PAYLOAD)
    )
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.approve", {"id": card_id}, "a-2"))
        cards, reply = collect_statuses_until(ws, {"executed", "failed"})
    assert reply["name"] == "ok"
    statuses = [card["status"] for card in cards if card["id"] == card_id]
    assert statuses == ["approved", "executing", "failed"]
    # This box's honest expected outcome: fail closed, plain-voice reason.
    assert "Google account not connected" in cards[-1]["error"]
    assert asyncio.run(db_card(tmp_db_path, card_id))[0] == "failed"


def test_approve_with_edited_payload_freezes_the_edit_as_what_executes(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    card_id = asyncio.run(seed_pending_card(tmp_db_path))
    edited = {"title": "Edited title", "body_markdown": "- edited body"}
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.approve", {"id": card_id, "edited_payload": edited}, "a-3"))
        cards, reply = collect_statuses_until(ws, {"executed", "failed"})
    assert reply["name"] == "ok"
    approved_event = next(card for card in cards if card["status"] == "approved")
    assert approved_event["payload"] == edited  # the edit rode the approve
    _, payload_json = asyncio.run(db_card(tmp_db_path, card_id))
    assert json.loads(payload_json) == edited
    # The executed note carries the EDITED body (what-you-approved-executes).
    inbox_notes = list((tmp_path / "Inbox").glob("*.md"))
    assert len(inbox_notes) == 1 and "- edited body" in inbox_notes[0].read_text(encoding="utf-8")


def test_approve_with_invalid_edited_payload_refuses_and_card_stays_pending(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    card_id = asyncio.run(seed_pending_card(tmp_db_path))
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        # body_markdown missing entirely: violates the typed payload model.
        ws.send_text(command("card.approve", {"id": card_id, "edited_payload": {"title": "x"}}))
        reply = next_relevant(ws)
    assert reply["name"] == "error" and reply["payload"]["code"] == "card_error"
    assert asyncio.run(db_card(tmp_db_path, card_id))[0] == "pending"


def test_approve_unknown_id_and_malformed_payloads_refuse_typed(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.approve", {"id": 999}, "u-1"))
        reply = next_relevant(ws)
        assert reply["name"] == "error" and reply["payload"]["code"] == "card_error"
        assert "does not exist" in reply["payload"]["message"]
        # Deny by default: bad id type, missing id, and extra fields refuse.
        for bad in ({"id": "1"}, {}, {"id": 1, "surprise": True}, {"id": 0}):
            ws.send_text(command("card.approve", bad))
            reply = next_relevant(ws)
            assert reply["name"] == "error", f"payload {bad!r}"
            assert reply["payload"]["code"] == "invalid_payload", f"payload {bad!r}"


def test_illegal_transitions_surface_as_typed_errors(tmp_db_path: Path, tmp_path: Path) -> None:
    failed_id = asyncio.run(
        seed_failed_card(tmp_db_path, card_type="write_note", payload_json=WRITE_NOTE_PAYLOAD)
    )
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        # approve on a failed (terminal) card: the status machine refuses.
        ws.send_text(command("card.approve", {"id": failed_id}, "t-1"))
        reply = next_relevant(ws)
        assert reply["name"] == "error" and reply["payload"]["code"] == "card_error"
        assert "'failed'" in reply["payload"]["message"]
        # dismiss on the same terminal card refuses too.
        ws.send_text(command("card.dismiss", {"id": failed_id}, "t-2"))
        reply = next_relevant(ws)
        assert reply["name"] == "error" and reply["payload"]["code"] == "card_error"
        # edited_payload on a non-pending card is refused explicitly.
        ws.send_text(
            command(
                "card.approve",
                {"id": failed_id, "edited_payload": {"title": "x", "body_markdown": "y"}},
            )
        )
        reply = next_relevant(ws)
        assert reply["name"] == "error"
        assert "only valid on a pending card" in reply["payload"]["message"]
    assert asyncio.run(db_card(tmp_db_path, failed_id))[0] == "failed"  # untouched


# ---------------------------------------------------------------- card.dismiss
def test_dismiss_broadcasts_card_updated_and_second_dismiss_refuses(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    card_id = asyncio.run(seed_pending_card(tmp_db_path))
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.dismiss", {"id": card_id}, "d-1"))
        cards, reply = collect_statuses_until(ws, {"dismissed"})
        assert reply["name"] == "ok" and reply["id"] == "d-1"
        assert [card["status"] for card in cards] == ["dismissed"]
        ws.send_text(command("card.dismiss", {"id": card_id}, "d-2"))
        reply = next_relevant(ws)
        assert reply["name"] == "error" and reply["payload"]["code"] == "card_error"
    assert asyncio.run(db_card(tmp_db_path, card_id))[0] == "dismissed"


# ------------------------------------------------------------------ card.retry
def test_retry_clones_the_failed_card_and_executes_the_clone(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    failed_id = asyncio.run(
        seed_failed_card(tmp_db_path, card_type="write_note", payload_json=WRITE_NOTE_PAYLOAD)
    )
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.retry", {"id": failed_id}, "r-1"))
        cards, reply = collect_statuses_until(ws, {"executed", "failed"})
    assert reply["name"] == "ok"
    clone_ids = {card["id"] for card in cards}
    assert failed_id not in clone_ids  # history is never rewritten (0008)
    clone_id = clone_ids.pop()
    statuses = [card["status"] for card in cards]
    # The clone appears pending, is approved by the retry click, executes.
    assert statuses == ["pending", "approved", "executing", "executed"]
    clone_status, clone_payload = asyncio.run(db_card(tmp_db_path, clone_id))
    assert clone_status == "executed"
    assert json.loads(clone_payload) == json.loads(WRITE_NOTE_PAYLOAD)  # exact clone
    assert asyncio.run(db_card(tmp_db_path, failed_id))[0] == "failed"  # untouched


def test_retry_on_a_pending_card_refuses(tmp_db_path: Path, tmp_path: Path) -> None:
    card_id = asyncio.run(seed_pending_card(tmp_db_path))
    app = make_app(tmp_db_path, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(command("card.retry", {"id": card_id}, "r-2"))
        reply = next_relevant(ws)
    assert reply["name"] == "error" and reply["payload"]["code"] == "card_error"
    assert "only valid on a failed card" in reply["payload"]["message"]
    assert asyncio.run(db_card(tmp_db_path, card_id))[0] == "pending"
