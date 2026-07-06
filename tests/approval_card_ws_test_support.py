"""Shared harness for the WS approval-card suites (list/approve/dismiss/retry).

Builds the REAL app + connection handler + gateway + repositories + executor
against a tmp_path SQLite database migrated with the REAL migration files
and a tmp_path synthetic vault. Google is a fake that fails closed with
"Google account not connected" — this box's real state. Card seeding walks
only LEGAL status paths (0008 triggers); frame helpers skip heartbeats and
collect every ``card.updated`` broadcast so tests assert the full status
story. No network anywhere (unit-test discipline).
"""

import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite
from starlette.testclient import WebSocketTestSession

from engine.google.google_auth_errors import GoogleNotConnectedError
from engine.google.google_session import GoogleSession
from engine.protocol import EventBroadcastHub
from engine.router.fallback_executor import ProviderRouter
from engine.server import create_app
from engine.storage import apply_migrations
from engine.stt.live_capture_service import LiveCaptureService
from engine.wiring.approval_cards_gateway import ApprovalCardsGateway
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
    """(status, payload_json) straight from the database — the ground truth."""
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
