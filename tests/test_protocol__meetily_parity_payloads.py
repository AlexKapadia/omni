"""Payload validation for Meetily-parity commands (export md, text replace, scoped ask)."""

import pytest
from pydantic import ValidationError

from engine.protocol.ask_query_payloads import MAX_ASK_QUERY_CHARS, AskQueryCommandPayload
from engine.protocol.meeting_finalization_payloads import (
    MeetingExportCommandPayload,
    MeetingTextReplacePayload,
)


def test_meeting_export_accepts_md_format() -> None:
    payload = MeetingExportCommandPayload.model_validate(
        {"meeting_id": "m-1", "format": "md"}
    )
    assert payload.format == "md"


def test_meeting_export_rejects_unknown_format() -> None:
    with pytest.raises(ValidationError):
        MeetingExportCommandPayload.model_validate({"meeting_id": "m-1", "format": "html"})


def test_meeting_text_replace_accepts_all_targets() -> None:
    for target in ("transcript", "enhanced_notes", "both"):
        payload = MeetingTextReplacePayload.model_validate(
            {
                "meeting_id": "m-1",
                "find": "Acme",
                "replace": "ACME",
                "target": target,
            }
        )
        assert payload.target == target


def test_meeting_text_replace_rejects_empty_find() -> None:
    with pytest.raises(ValidationError):
        MeetingTextReplacePayload.model_validate(
            {"meeting_id": "m-1", "find": "", "replace": "x", "target": "transcript"}
        )


def test_meeting_text_replace_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MeetingTextReplacePayload.model_validate(
            {
                "meeting_id": "m-1",
                "find": "a",
                "replace": "b",
                "target": "both",
                "replace_all": True,
            }
        )


def test_ask_query_accepts_optional_meeting_id() -> None:
    bare = AskQueryCommandPayload.model_validate({"query": "hello"})
    assert bare.meeting_id is None
    scoped = AskQueryCommandPayload.model_validate(
        {"query": "hello", "meeting_id": "m-42"}
    )
    assert scoped.meeting_id == "m-42"


def test_ask_query_rejects_empty_meeting_id() -> None:
    with pytest.raises(ValidationError):
        AskQueryCommandPayload.model_validate({"query": "hi", "meeting_id": ""})


def test_ask_query_query_bound_still_applies_with_meeting_id() -> None:
    with pytest.raises(ValidationError):
        AskQueryCommandPayload.model_validate(
            {"query": "x" * (MAX_ASK_QUERY_CHARS + 1), "meeting_id": "m-1"}
        )
