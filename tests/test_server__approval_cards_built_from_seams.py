"""Card-building seams: finalization events and dictation intents -> PENDING cards.

Drives the REAL ``ApprovalCardBuildWiring`` against a tmp_path SQLite
database migrated with the REAL migration files, pinning:
- ``enhance.ready``/``enhance.failed`` for a FINALIZED meeting builds
  pending cards from the newest extraction row and broadcasts one
  ``card.updated`` per created card;
- a NOT-finalized meeting builds nothing (fail closed — ``enhance.failed``
  also fires for refused runs);
- re-delivery is idempotent (no duplicate cards);
- a recorded dictation intent becomes at most one pending card via the
  gateway's post-final hook, and the hook path is SUGGEST-ONLY.
"""

from pathlib import Path
from typing import Any

from engine.approval_card_build_server_wiring import ApprovalCardBuildWiring
from engine.dictation.dictation_finalization import DictationFinalResult
from engine.dictation.dictation_intent_schema import DictationIntentType, ParsedIntent
from engine.dictation.dictation_intents_repository import insert_dictation_intent
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.dictation_command_dispatcher import DictationCommandGateway
from engine.protocol import Envelope, EventBroadcastHub
from engine.storage import apply_migrations, open_sqlite_connection
from tests.conftest import REPO_ROOT

MIGRATIONS = REPO_ROOT / "migrations"
TS = "2026-07-06T12:00:00+00:00"

EXTRACTION_PAYLOAD = (
    '{"contacts": [{"name": "Priya Patel", "email": "priya@example.com"}],'
    ' "dates": [{"what": "Send the proposal", "when": "Friday"}]}'
)


class EventRecorder:
    """Hub subscriber that keeps every broadcast envelope (offline)."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[Envelope] = []
        hub.subscribe(self._record)

    async def _record(self, envelope: Envelope) -> None:
        self.events.append(envelope)

    def card_updates(self) -> list[dict[str, Any]]:
        return [
            dict(e.payload["card"]) for e in self.events if e.name == "card.updated"
        ]


async def seed_meeting_with_extraction(
    tmp_db: Path, *, finalized: bool, meeting_id: str = "m-1"
) -> None:
    await apply_migrations(tmp_db, MIGRATIONS)
    connection = await open_sqlite_connection(tmp_db)
    try:
        await connection.execute(
            "INSERT INTO meetings (id, title, started_at, finalized_at)"
            " VALUES (?, 'Weekly sync', ?, ?)",
            (meeting_id, TS, TS if finalized else None),
        )
        await connection.execute(
            "INSERT INTO extraction_results (meeting_id, ts, payload_json) VALUES (?, ?, ?)",
            (meeting_id, TS, EXTRACTION_PAYLOAD),
        )
    finally:
        await connection.close()


async def all_cards(tmp_db: Path) -> list[tuple[str, str, str | None]]:
    connection = await open_sqlite_connection(tmp_db)
    try:
        cursor = await connection.execute(
            "SELECT card_type, status, meeting_id FROM approval_cards ORDER BY id"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [(str(r[0]), str(r[1]), None if r[2] is None else str(r[2])) for r in rows]
    finally:
        await connection.close()


# ------------------------------------------------------- finalization seam
async def test_enhance_ready_on_finalized_meeting_builds_pending_cards(
    tmp_db_path: Path,
) -> None:
    await seed_meeting_with_extraction(tmp_db_path, finalized=True)
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await hub.broadcast_event("enhance.ready", {"meeting_id": "m-1", "note_path": "n.md"})
    await wiring.drain()
    cards = await all_cards(tmp_db_path)
    # One contact card + one event card, all born pending, meeting-bound.
    assert cards == [
        ("upsert_contact", "pending", "m-1"),
        ("create_event", "pending", "m-1"),
    ]
    updates = recorder.card_updates()
    assert [card["status"] for card in updates] == ["pending", "pending"]
    assert {card["card_type"] for card in updates} == {"upsert_contact", "create_event"}
    await wiring.shutdown()


async def test_enhance_failed_still_builds_when_finalization_recorded(
    tmp_db_path: Path,
) -> None:
    # enhance failed but the run finalized (extraction may have succeeded):
    # the DB — not the event name — decides.
    await seed_meeting_with_extraction(tmp_db_path, finalized=True)
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await hub.broadcast_event("enhance.failed", {"meeting_id": "m-1", "reason": "no keys"})
    await wiring.drain()
    assert len(await all_cards(tmp_db_path)) == 2
    await wiring.shutdown()


async def test_not_finalized_meeting_builds_nothing_fail_closed(tmp_db_path: Path) -> None:
    # A refused finalize also broadcasts enhance.failed; no cards may appear.
    await seed_meeting_with_extraction(tmp_db_path, finalized=False)
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await hub.broadcast_event("enhance.failed", {"meeting_id": "m-1", "reason": "refused"})
    await wiring.drain()
    assert await all_cards(tmp_db_path) == []
    await wiring.shutdown()


async def test_event_redelivery_is_idempotent_no_duplicate_cards(tmp_db_path: Path) -> None:
    await seed_meeting_with_extraction(tmp_db_path, finalized=True)
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    for _ in range(3):
        await hub.broadcast_event("enhance.ready", {"meeting_id": "m-1", "note_path": "n.md"})
    await wiring.drain()
    assert len(await all_cards(tmp_db_path)) == 2  # exact-duplicate suggestions skipped
    await wiring.shutdown()


async def test_malformed_meeting_id_and_unknown_meeting_are_ignored(tmp_db_path: Path) -> None:
    await apply_migrations(tmp_db_path, MIGRATIONS)
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await hub.broadcast_event("enhance.ready", {"meeting_id": 42})  # type-guarded: skipped
    await hub.broadcast_event("enhance.ready", {"meeting_id": "ghost", "note_path": "x"})
    await wiring.drain()
    assert await all_cards(tmp_db_path) == []
    await wiring.shutdown()


# --------------------------------------------------------- dictation seam
async def seed_dictation_intent(tmp_db: Path, *, confidence: float) -> int:
    await apply_migrations(tmp_db, MIGRATIONS)
    connection = await open_sqlite_connection(tmp_db)
    try:
        return await insert_dictation_intent(
            connection,
            ts=TS,
            raw_text="Omni, remind me to send the deck",
            intent=ParsedIntent(
                intent_type=DictationIntentType.WRITE_NOTE,
                fields={"title": "Send the deck", "body": "send the deck to Priya"},
                confidence=confidence,
            ),
            provider="groq",
            model="test-model",
        )
    finally:
        await connection.close()


def command_result(intent_row_id: int | None) -> DictationFinalResult:
    return DictationFinalResult(
        mode=DictationMode.COMMAND,
        text="Omni, remind me to send the deck",
        intent_row_id=intent_row_id,
    )


async def test_dictation_intent_becomes_one_pending_card_with_broadcast(
    tmp_db_path: Path,
) -> None:
    row_id = await seed_dictation_intent(tmp_db_path, confidence=0.9)
    hub = EventBroadcastHub()
    recorder = EventRecorder(hub)
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await wiring.on_dictation_final(command_result(row_id))
    cards = await all_cards(tmp_db_path)
    assert cards == [("write_note", "pending", None)]  # dictation is not meeting-bound
    updates = recorder.card_updates()
    assert len(updates) == 1 and updates[0]["status"] == "pending"
    assert updates[0]["source"] == "dictation"
    # Re-running the hook is idempotent (exact duplicate skipped).
    await wiring.on_dictation_final(command_result(row_id))
    assert len(await all_cards(tmp_db_path)) == 1
    await wiring.shutdown()


async def test_low_confidence_intent_and_no_intent_build_nothing(tmp_db_path: Path) -> None:
    row_id = await seed_dictation_intent(tmp_db_path, confidence=0.2)  # below the 0.6 floor
    hub = EventBroadcastHub()
    wiring = ApprovalCardBuildWiring(hub, db_path=tmp_db_path, migrations_dir=MIGRATIONS)
    await wiring.on_dictation_final(command_result(row_id))
    await wiring.on_dictation_final(command_result(None))  # note/inject release: no intent
    assert await all_cards(tmp_db_path) == []
    await wiring.shutdown()


async def test_dictation_gateway_invokes_the_hook_and_survives_hook_failure(
    tmp_db_path: Path,
) -> None:
    """The gateway's post-final hook fires per release and NEVER fails it."""
    hub = EventBroadcastHub()
    seen: list[DictationFinalResult] = []

    class FakeSession:
        last_flush_ms = 12

        async def end(self) -> str:
            return "hello world"

    async def fake_finalize(
        text: str, inject_requested: bool, flush_ms: int | None
    ) -> DictationFinalResult:
        return DictationFinalResult(mode=DictationMode.NOTE, text=text, flush_ms=flush_ms)

    gateway = DictationCommandGateway(
        hub=hub,
        db_path=tmp_db_path,
        migrations_dir=MIGRATIONS,
        session_service=FakeSession(),  # type: ignore[arg-type]
        release_finalize=fake_finalize,
    )

    async def hook(result: DictationFinalResult) -> None:
        seen.append(result)
        raise RuntimeError("hook exploded")  # must not fail the release

    gateway.on_final_result = hook
    result = await gateway.end(inject_requested=False)
    assert result.text == "hello world"
    assert len(seen) == 1 and seen[0].flush_ms == 12
