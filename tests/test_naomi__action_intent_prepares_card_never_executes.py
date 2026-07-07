"""Naomi action path: prepares a PENDING approval card and NEVER executes.

Security invariant under test (§5.6 approval-before-execute, deny by default):
- An imperative utterance becomes a PENDING card only; Naomi confirms it.
- The card is born 'pending' and is NOT claimable for execution — the ONLY
  path to a tool (execute_approved_card) refuses a pending card, so nothing
  Naomi prepares can run without an explicit approval elsewhere.
- A question triggers no router call and no card (the deterministic gate).
- Below-confidence intents are recorded but never surfaced as a card.
"""

import json
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from engine.agents.agents_errors import CardNotExecutableError
from engine.agents.approval_cards_repository import get_card
from engine.agents.card_executor import execute_approved_card
from engine.agents.default_tool_registry import build_default_tool_registry
from engine.naomi.naomi_action_intent_flow import (
    NaomiActionIntentFlow,
    looks_like_action_request,
)
from engine.router.completion_contract import Provider, ProviderCompletion, RoutedCompletion
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations


class IntentRouter:
    """Returns a canned intent JSON; records whether it was called."""

    def __init__(self, intent: dict[str, Any] | None) -> None:
        self._intent = intent
        self.calls = 0

    async def route(
        self, task_type: str, system_frame: str, messages: object, **kwargs: object
    ) -> RoutedCompletion:
        self.calls += 1
        text = json.dumps(self._intent) if self._intent is not None else "{}"
        completion = ProviderCompletion(
            text=text, provider=Provider.GROQ, model="m", prompt_tokens=1, completion_tokens=1
        )
        return RoutedCompletion(
            completion=completion, provider=Provider.GROQ, model="m", latency_ms=5
        )


async def _open_db(tmp_path: Path) -> aiosqlite.Connection:
    db_path = tmp_path / "naomi-action.db"
    migrations = Path(__file__).resolve().parent.parent / "migrations"
    await apply_migrations(db_path, migrations)
    return await open_sqlite_connection(db_path)


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("Schedule a review with Priya on Friday", True),
        ("Draft an email to Sanjay about the renewal", True),
        ("add John Doe to my contacts", True),
        ("When is the Henderson contract renewal due?", False),
        ("What did we decide about pricing?", False),
        ("", False),
        ("   ", False),
    ],
)
def test_deterministic_action_gate(utterance: str, expected: bool) -> None:
    assert looks_like_action_request(utterance) is expected


async def test_question_makes_no_router_call_and_no_card(tmp_path: Path) -> None:
    connection = await _open_db(tmp_path)
    try:
        router = IntentRouter(None)
        flow = NaomiActionIntentFlow(
            connection, router, now_iso=lambda: "2026-07-07T00:00:00+00:00", clock=lambda: 0.0
        )
        result = await flow.maybe_prepare_action("When is the Henderson renewal due?")
        assert result is None
        assert router.calls == 0  # the gate short-circuits before any egress
    finally:
        await connection.close()


async def test_action_prepares_pending_card_that_cannot_be_executed(tmp_path: Path) -> None:
    connection = await _open_db(tmp_path)
    try:
        intent = {
            "intent_type": "create_event",
            "fields": {"title": "review with Priya", "when": "Friday"},
            "confidence": 0.92,
        }
        router = IntentRouter(intent)
        clock_values = iter([1.0, 1.25])
        flow = NaomiActionIntentFlow(
            connection,
            router,
            now_iso=lambda: "2026-07-07T09:00:00+00:00",
            clock=lambda: next(clock_values),
        )
        result = await flow.maybe_prepare_action("Schedule a review with Priya on Friday")
        assert result is not None
        assert result.card_type == "create_event"
        assert "prepared" in result.spoken_confirmation.lower()
        assert result.llm_ms == 250  # (1.25 - 1.0) * 1000, exact

        # The card exists and is PENDING.
        card = await get_card(connection, result.card_id)
        assert card is not None
        assert card.status == "pending"

        # NEVER-EXECUTE: the only path to a tool refuses a pending card.
        registry = build_default_tool_registry(tmp_path)
        with pytest.raises(CardNotExecutableError):
            await execute_approved_card(
                connection,
                result.card_id,
                registry=registry,
                google_session=None,  # type: ignore[arg-type]  # unreachable: claim fails first
                vault_root=tmp_path,
            )
        # Still pending after the refused execution — nothing ran.
        card_after = await get_card(connection, result.card_id)
        assert card_after is not None and card_after.status == "pending"
    finally:
        await connection.close()


async def test_low_confidence_intent_records_but_builds_no_card(tmp_path: Path) -> None:
    connection = await _open_db(tmp_path)
    try:
        intent = {
            "intent_type": "create_event",
            "fields": {"title": "maybe something"},
            "confidence": 0.2,  # below the 0.6 floor
        }
        router = IntentRouter(intent)
        flow = NaomiActionIntentFlow(
            connection, router, now_iso=lambda: "2026-07-07T09:00:00+00:00", clock=lambda: 0.0
        )
        result = await flow.maybe_prepare_action("Schedule something vague maybe")
        assert result is None  # not surfaced as an action
        assert router.calls == 1  # it WAS classified (recorded for audit)
    finally:
        await connection.close()
