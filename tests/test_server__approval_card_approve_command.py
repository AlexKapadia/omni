"""WS ``card.approve``: execution walk, fail-closed Google, edits, refusals.

Drives the REAL app + connection handler + gateway + executor against a
tmp_path SQLite database migrated with the REAL migration files and a
tmp_path synthetic vault (harness in
``tests/approval_card_ws_test_support.py``). Asserts the ``card.updated``
broadcast on EVERY status change (approved, executing, executed/failed) and
every refusal path (validation, unknown id) as typed errors.
"""

import asyncio
import json
from pathlib import Path

from starlette.testclient import TestClient

from tests.approval_card_ws_test_support import (
    EVENT_PAYLOAD,
    collect_statuses_until,
    command,
    db_card,
    make_app,
    next_relevant,
    seed_pending_card,
)


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
