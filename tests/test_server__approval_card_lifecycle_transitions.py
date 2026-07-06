"""WS card lifecycle transitions: ``card.dismiss`` / ``card.retry`` / illegal
moves on terminal cards.

Drives the REAL app + connection handler + gateway + executor against a
tmp_path SQLite database migrated with the REAL migration files (harness in
``tests/approval_card_ws_test_support.py``). Proves the status machine
refuses every illegal transition as a typed error, dismiss broadcasts and is
terminal, and retry clones the failed card (history is never rewritten).
"""

import asyncio
import json
from pathlib import Path

from starlette.testclient import TestClient

from tests.approval_card_ws_test_support import (
    WRITE_NOTE_PAYLOAD,
    collect_statuses_until,
    command,
    db_card,
    make_app,
    next_relevant,
    seed_failed_card,
    seed_pending_card,
)


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
