"""WS ``cards.list``: empty database and the pinned card shape, newest first.

Drives the REAL app + connection handler + gateway against a tmp_path SQLite
database migrated with the REAL migration files (harness in
``tests/approval_card_ws_test_support.py``). Command names pinned to
``engine/agents/approval_protocol_names.py``.
"""

import asyncio
from pathlib import Path

from starlette.testclient import TestClient

from tests.approval_card_ws_test_support import (
    command,
    make_app,
    next_relevant,
    seed_pending_card,
)


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
