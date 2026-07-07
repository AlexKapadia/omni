"""LLM fallback mapper + dictation payload normalisation + card payloads.

Three surfaces:

- ``map_via_router_function_call``: the UNTRUSTED-model fallback. The model's
  proposed arguments must pass the tool's own pydantic model exactly or the
  mapping fails typed (fail closed). No-router, no-call, bad-JSON, and
  schema-violation paths are all asserted to refuse — nothing half-validated
  reaches a tool.
- ``_clean_schema_node``: strips provider-hostile annotation keys
  (``additionalProperties``/``title``) while a field literally named ``title``
  survives — the exact live-check lesson the code documents.
- ``_dictation_payload`` + ``build_cards_from_extraction``: deterministic
  field normalisation with exact-value assertions (the parser's fallbacks and
  the built cards would fail these if a field were mapped wrong).
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_builder import build_cards_from_extraction
from engine.agents.approval_card_types import (
    ApprovalCardRecord,
    CardType,
    CreateEventCardPayload,
    DraftEmailCardPayload,
    UpsertContactCardPayload,
    WriteNoteCardPayload,
)
from engine.agents.approval_cards_repository import list_cards
from engine.agents.calendar_create_event_tool import CalendarCreateEventParams
from engine.agents.calendar_find_free_slot_tool import (
    CalendarFindFreeSlotParams,
    CalendarFindFreeSlotTool,
)
from engine.agents.contacts_upsert_tool import ContactsUpsertParams
from engine.agents.dictation_intent_card_builder import _dictation_payload
from engine.agents.llm_function_call_mapper import (
    _clean_schema_node,
    function_declaration_schema,
    map_via_router_function_call,
)
from engine.dictation.dictation_intents_repository import DictationIntentRecord
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
    ToolCall,
    ToolSpec,
)
from engine.router.fallback_executor import ProviderRouter
from tests.agents_test_support import TS, insert_meeting, migrated_connection

_WIN_START = "2026-07-06T09:00:00+00:00"
_WIN_END = "2026-07-06T17:00:00+00:00"


# --------------------------------------------------------------------------
# A stub router: a real ProviderRouter subclass (mypy-clean) that returns a
# canned RoutedCompletion and records exactly what it was asked to route.
# --------------------------------------------------------------------------


class _StubRouter(ProviderRouter):
    def __init__(self, tool_calls: tuple[ToolCall, ...]) -> None:
        self.calls: list[tuple[str, str, tuple[ChatMessage, ...]]] = []
        self._routed = RoutedCompletion(
            completion=ProviderCompletion(
                text="",
                provider=Provider.GROQ,
                model="stub-model",
                prompt_tokens=1,
                completion_tokens=1,
                tool_calls=tool_calls,
            ),
            provider=Provider.GROQ,
            model="stub-model",
            latency_ms=1,
        )

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        self.calls.append((task_type, system_frame, messages))
        return self._routed


def _card_record(payload_json: str) -> ApprovalCardRecord:
    return ApprovalCardRecord(
        id=1,
        meeting_id=None,
        source="dictation",
        source_row_id=1,
        card_type="find_slot",
        payload_json=payload_json,
        status="approved",
        created_at=TS,
        decided_at=TS,
        executed_at=None,
        result_json=None,
        error=None,
    )


def _call(name: str, arguments: object) -> ToolCall:
    args_json = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ToolCall(name=name, arguments_json=args_json)


_VALID_SLOT_ARGS = {
    "duration_minutes": 30,
    "window_start_iso": _WIN_START,
    "window_end_iso": _WIN_END,
}


# --------------------------------------------------------------------------
# map_via_router_function_call
# --------------------------------------------------------------------------


async def test_no_router_refuses_with_reason() -> None:
    tool = CalendarFindFreeSlotTool()
    with pytest.raises(ToolExecutionError, match="no router") as excinfo:
        await map_via_router_function_call(
            None, tool, _card_record("{}"), "needs resolution"
        )
    assert "needs resolution" in str(excinfo.value)
    assert excinfo.value.tool_name == tool.name


async def test_model_that_calls_nothing_refuses() -> None:
    tool = CalendarFindFreeSlotTool()
    router = _StubRouter(())  # the model declined to call the function
    with pytest.raises(ToolExecutionError, match="did not produce a function call"):
        await map_via_router_function_call(router, tool, _card_record("{}"), "why")


async def test_model_calling_a_different_tool_is_ignored_and_refuses() -> None:
    tool = CalendarFindFreeSlotTool()
    router = _StubRouter((_call("some_other_tool", _VALID_SLOT_ARGS),))
    with pytest.raises(ToolExecutionError, match="did not produce a function call"):
        await map_via_router_function_call(router, tool, _card_record("{}"), "why")


async def test_model_arguments_not_json_refuses() -> None:
    tool = CalendarFindFreeSlotTool()
    router = _StubRouter((_call(tool.name, "{not valid json"),))
    with pytest.raises(ToolExecutionError, match="failed validation"):
        await map_via_router_function_call(router, tool, _card_record("{}"), "why")


async def test_model_arguments_violating_schema_refuses() -> None:
    """duration_minutes=0 is below the ge=1 bound: fail closed on bad args."""
    tool = CalendarFindFreeSlotTool()
    bad = {**_VALID_SLOT_ARGS, "duration_minutes": 0}
    router = _StubRouter((_call(tool.name, bad),))
    with pytest.raises(ToolExecutionError, match="failed validation"):
        await map_via_router_function_call(router, tool, _card_record("{}"), "why")


async def test_valid_model_call_returns_params_and_provider() -> None:
    tool = CalendarFindFreeSlotTool()
    router = _StubRouter((_call(tool.name, _VALID_SLOT_ARGS),))
    record = _card_record('{"duration_minutes": 30}')
    params, provider_name = await map_via_router_function_call(
        router, tool, record, "window is natural language"
    )
    assert isinstance(params, CalendarFindFreeSlotParams)
    assert params.duration_minutes == 30
    assert params.window_start_iso == _WIN_START
    assert params.window_end_iso == _WIN_END
    assert provider_name == "groq"
    # The router was driven on the agentic-tools task, with the card payload
    # carried as DATA in the user message (injection posture).
    task_type, system_frame, messages = router.calls[0]
    assert task_type == "agentic_tools"
    assert "reference time" in system_frame or "reference" in system_frame.lower()
    assert record.payload_json in messages[0].content
    assert "window is natural language" in messages[0].content


# --------------------------------------------------------------------------
# function_declaration_schema / _clean_schema_node
# --------------------------------------------------------------------------


def test_schema_strips_annotations_but_keeps_field_named_title() -> None:
    schema = function_declaration_schema(CalendarCreateEventParams)
    # Annotation keys the providers reject are gone at the top level...
    assert "additionalProperties" not in schema
    assert "title" not in schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    # ...but the real field literally named "title" survives (live-check #2).
    assert "title" in properties
    title_schema = properties["title"]
    assert isinstance(title_schema, dict)
    assert "title" not in title_schema  # its annotation title IS stripped
    # A list field's "items" child schema is recursed into, not dropped.
    attendees = properties["attendee_emails"]
    assert isinstance(attendees, dict)
    assert "items" in attendees


def test_schema_recurses_into_anyof_optional_fields() -> None:
    schema = function_declaration_schema(ContactsUpsertParams)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    phone = properties["phone"]
    assert isinstance(phone, dict)
    assert "anyOf" in phone  # optional str|None keeps its anyOf branches
    assert "title" not in phone


def test_clean_schema_node_recurses_into_defs() -> None:
    """A nested model produces a $defs map; its annotation keys are stripped
    while structure (property names) survives — the $defs map-key branch."""

    class _Inner(BaseModel):
        label: str

    class _Outer(BaseModel):
        inner: _Inner

    cleaned = _clean_schema_node(_Outer.model_json_schema())
    assert "$defs" in cleaned
    defs = cleaned["$defs"]
    assert isinstance(defs, dict)
    inner_schema = defs["_Inner"]
    assert isinstance(inner_schema, dict)
    assert "title" not in inner_schema  # nested annotation title stripped
    inner_props = inner_schema["properties"]
    assert isinstance(inner_props, dict)
    assert "label" in inner_props  # property name preserved


# --------------------------------------------------------------------------
# _dictation_payload: deterministic normalisation, exact outputs
# --------------------------------------------------------------------------


def _intent(raw_text: str = "Omni, do the thing") -> DictationIntentRecord:
    return DictationIntentRecord(
        id=1,
        ts=TS,
        raw_text=raw_text,
        intent_type="ignored-here",
        fields_json="{}",
        confidence=0.9,
        provider="groq",
        model="test",
    )


def test_create_event_title_falls_back_through_event_and_what_keys() -> None:
    payload = _dictation_payload(
        CardType.CREATE_EVENT, {"event": "Standup", "date": "Mon", "time": "9am"}, _intent()
    )
    assert isinstance(payload, CreateEventCardPayload)
    assert payload.title == "Standup"  # 'title' absent -> 'event'
    assert payload.when_hint == "Mon 9am"  # when-parts joined in key order


def test_create_event_title_falls_back_to_raw_text() -> None:
    payload = _dictation_payload(CardType.CREATE_EVENT, {}, _intent("Buy milk"))
    assert isinstance(payload, CreateEventCardPayload)
    assert payload.title == "Buy milk"
    assert payload.when_hint is None


def test_create_event_with_no_title_source_returns_none() -> None:
    """Empty fields AND empty raw text -> unactionable, refused (None)."""
    assert _dictation_payload(CardType.CREATE_EVENT, {}, _intent("")) is None


def test_upsert_contact_name_falls_back_to_person_key() -> None:
    payload = _dictation_payload(
        CardType.UPSERT_CONTACT, {"person": "Ana Cruz", "phone": "123"}, _intent()
    )
    assert isinstance(payload, UpsertContactCardPayload)
    assert payload.name == "Ana Cruz"
    assert payload.phone == "123"


def test_upsert_contact_without_name_returns_none() -> None:
    assert _dictation_payload(CardType.UPSERT_CONTACT, {"phone": "123"}, _intent()) is None


def test_draft_email_without_recipient_yields_empty_to_list() -> None:
    payload = _dictation_payload(CardType.DRAFT_EMAIL, {"subject": "Hi"}, _intent())
    assert isinstance(payload, DraftEmailCardPayload)
    assert payload.to == []  # no recipient key -> empty, never invented
    assert payload.subject == "Hi"
    assert payload.body_hint is None


def test_draft_email_recipient_and_body_fall_back_through_keys() -> None:
    payload = _dictation_payload(
        CardType.DRAFT_EMAIL, {"recipient": "a@b.io", "message": "See you"}, _intent()
    )
    assert isinstance(payload, DraftEmailCardPayload)
    assert payload.to == ["a@b.io"]
    assert payload.body_hint == "See you"


def test_write_note_title_and_body_fall_back_through_keys() -> None:
    payload = _dictation_payload(
        CardType.WRITE_NOTE, {"topic": "Ideas", "note": "ship it"}, _intent()
    )
    assert isinstance(payload, WriteNoteCardPayload)
    assert payload.title == "Ideas"
    assert payload.body_markdown == "ship it"


def test_write_note_without_title_uses_dated_default() -> None:
    payload = _dictation_payload(CardType.WRITE_NOTE, {"content": "notes here"}, _intent())
    assert isinstance(payload, WriteNoteCardPayload)
    assert payload.title == "Dictated note 2026-07-06"  # ts[:10]
    assert payload.body_markdown == "notes here"


def test_write_note_without_body_returns_none() -> None:
    assert _dictation_payload(CardType.WRITE_NOTE, {}, _intent("")) is None


# --------------------------------------------------------------------------
# build_cards_from_extraction: exact payloads land on the created cards
# --------------------------------------------------------------------------


async def test_extraction_contact_card_carries_exact_fields(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_meeting(conn)
        result = await build_cards_from_extraction(
            conn,
            meeting_id="m-1",
            extraction_row_id=5,
            payload_json=json.dumps(
                {
                    "contacts": [
                        {
                            "name": "Elena Fischer",
                            "phone": "+49 30 000",
                            "email": "elena@nw.io",
                            "company": "Northwind",
                        }
                    ]
                }
            ),
            created_at=TS,
        )
        assert len(result.created_card_ids) == 1
        card = (await list_cards(conn))[0]
        assert card.card_type == "upsert_contact"
        payload = json.loads(card.payload_json)
        assert payload == {
            "name": "Elena Fischer",
            "phone": "+49 30 000",
            "email": "elena@nw.io",
            "company": "Northwind",
            "sync_to_google": False,  # deny-by-default: never auto-synced
        }
    finally:
        await conn.close()


async def test_extraction_date_becomes_event_card_with_when_hint(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    conn = await migrated_connection(tmp_db_path, real_migrations_dir)
    try:
        await insert_meeting(conn)
        result = await build_cards_from_extraction(
            conn,
            meeting_id="m-1",
            extraction_row_id=6,
            payload_json=json.dumps(
                {"dates": [{"what": "Contract review", "when": "next Tuesday 10:00"}]}
            ),
            created_at=TS,
        )
        assert len(result.created_card_ids) == 1
        card = (await list_cards(conn))[0]
        assert card.card_type == "create_event"
        payload = json.loads(card.payload_json)
        # The time stays a HINT (unresolved) for the executor to resolve later;
        # no explicit ISO is invented here.
        assert payload["title"] == "Contract review"
        assert payload["when_hint"] == "next Tuesday 10:00"
        assert payload["start_iso"] is None
        assert payload["end_iso"] is None
    finally:
        await conn.close()
