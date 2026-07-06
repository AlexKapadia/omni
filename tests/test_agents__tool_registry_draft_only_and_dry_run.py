"""Draft-only invariant + registry surface + dry-run preview exactness.

Security invariant under test (binding, claude.md §5.6): Gmail is
DRAFT-ONLY. The registry must expose NO send capability of any kind, and
the source code of engine/google + engine/agents must not reference the
Gmail send endpoint or send scope anywhere — the capability must be ABSENT
from the codebase, not merely unused. A source-scanning test enforces
that; registry and scope tests pin the surface; dry-run tests pin the
previews the approval card UI shows.
"""

from pathlib import Path

import pytest

from engine.agents.approval_card_types import CardType
from engine.agents.calendar_create_event_tool import CalendarCreateEventParams
from engine.agents.contacts_upsert_tool import ContactsUpsertParams
from engine.agents.default_tool_registry import build_default_tool_registry
from engine.agents.gmail_create_draft_tool import GmailCreateDraftParams
from engine.agents.tool_registry import ToolRegistry
from engine.agents.vault_write_note_tool import VaultWriteNoteParams
from engine.google.oauth_desktop_flow import GOOGLE_OAUTH_SCOPES

REPO_ROOT = Path(__file__).resolve().parent.parent

# Substrings whose PRESENCE anywhere in the Google/agents sources would mean
# a send capability exists (endpoint method, REST path, or OAuth scope).
FORBIDDEN_SEND_MARKERS = (
    "messages.send",
    "messages/send",
    "gmail.send",
    "drafts.send",
    "drafts/send",
)


def _source_files() -> list[Path]:
    files = sorted((REPO_ROOT / "engine" / "google").glob("*.py")) + sorted(
        (REPO_ROOT / "engine" / "agents").glob("*.py")
    )
    assert len(files) >= 15, "scan target looks wrong — did the packages move?"
    return files


@pytest.mark.parametrize("marker", FORBIDDEN_SEND_MARKERS)
def test_no_send_endpoint_or_scope_exists_anywhere_in_the_sources(marker: str) -> None:
    """Grep-style scan: the send capability must be absent from the code."""
    offenders = [
        path.name
        for path in _source_files()
        if marker in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"draft-only violation: {marker!r} found in {offenders}"


def test_registry_exposes_exactly_the_five_card_types(tmp_path: Path) -> None:
    registry = build_default_tool_registry(tmp_path)
    assert registry.registered_card_types() == frozenset(CardType)
    assert len(frozenset(CardType)) == 5  # adding a capability must be loud


def test_no_tool_name_suggests_sending(tmp_path: Path) -> None:
    registry = build_default_tool_registry(tmp_path)
    for name in registry.tool_names():
        assert "send" not in name.lower(), f"tool {name!r} violates draft-only naming"


def test_gmail_tool_is_the_draft_tool_and_nothing_else(tmp_path: Path) -> None:
    registry = build_default_tool_registry(tmp_path)
    tool = registry.tool_for_card_type("draft_email")
    assert tool.name == "gmail_create_draft"
    # The params model has no field that could flip a draft into a send.
    assert set(GmailCreateDraftParams.model_fields) == {"to", "subject", "body_text"}


def test_oauth_scopes_are_pinned_to_exactly_three() -> None:
    assert GOOGLE_OAUTH_SCOPES == (
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/contacts",
        "https://www.googleapis.com/auth/gmail.compose",
    )


def test_duplicate_card_type_registration_is_refused(tmp_path: Path) -> None:
    registry = build_default_tool_registry(tmp_path)
    tool = registry.tool_for_card_type("write_note")
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry((tool, tool))


def test_unknown_card_type_is_denied(tmp_path: Path) -> None:
    from engine.agents.agents_errors import UnknownCardTypeError

    registry = build_default_tool_registry(tmp_path)
    with pytest.raises(UnknownCardTypeError):
        registry.tool_for_card_type("send_email")  # the capability that must not be


# --- dry-run preview exactness (what the approval card shows is pinned) ---


def test_create_event_dry_run_preview_is_exact(tmp_path: Path) -> None:
    tool = build_default_tool_registry(tmp_path).tool_for_card_type("create_event")
    params = CalendarCreateEventParams(
        title="Contract review",
        start_iso="2026-07-10T13:00:00+00:00",
        end_iso="2026-07-10T14:00:00+00:00",
        attendee_emails=["tom@reed.io"],
    )
    assert tool.dry_run(params) == (
        "Event: Contract review",
        "From 2026-07-10T13:00:00+00:00 to 2026-07-10T14:00:00+00:00",
        "Invite: tom@reed.io",
    )


def test_gmail_draft_dry_run_states_the_draft_only_promise(tmp_path: Path) -> None:
    tool = build_default_tool_registry(tmp_path).tool_for_card_type("draft_email")
    params = GmailCreateDraftParams(
        to=["tom@reed.io"], subject="Contract terms", body_text="Hi Tom,\nDraft attached."
    )
    lines = tool.dry_run(params)
    assert lines == (
        "Draft to: tom@reed.io",
        "Subject: Contract terms",
        "Starts: Hi Tom,",
        "Draft only — nothing is ever dispatched",
    )


def test_contact_dry_run_says_vault_only_by_default(tmp_path: Path) -> None:
    tool = build_default_tool_registry(tmp_path).tool_for_card_type("upsert_contact")
    params = ContactsUpsertParams(name="Elena Fischer", email="elena@northwind.io")
    lines = tool.dry_run(params)
    assert lines == (
        "Contact: Elena Fischer",
        "Email: elena@northwind.io",
        "Vault only (no Google)",  # deny-by-default sync, stated to the user
    )
    synced = ContactsUpsertParams(name="Elena Fischer", sync_to_google=True)
    assert tool.dry_run(synced)[-1] == "Also sync to Google Contacts"


def test_write_note_dry_run_is_exact(tmp_path: Path) -> None:
    tool = build_default_tool_registry(tmp_path).tool_for_card_type("write_note")
    params = VaultWriteNoteParams(title="Demo ideas", body_markdown="First line\nSecond")
    assert tool.dry_run(params) == (
        "Note: Demo ideas",
        "Starts: First line",
        "Saved to Inbox/",
    )


def test_dry_run_refuses_mismatched_params(tmp_path: Path) -> None:
    """Handing the wrong params object to a tool must refuse, never guess."""
    from engine.agents.agents_errors import ToolExecutionError

    tool = build_default_tool_registry(tmp_path).tool_for_card_type("write_note")
    wrong = ContactsUpsertParams(name="Not a note")
    with pytest.raises(ToolExecutionError, match="expected VaultWriteNoteParams"):
        tool.dry_run(wrong)


# --- function-declaration schema sanitisation (live-check regression) ---


def test_function_declaration_schemas_carry_no_provider_hostile_keys(
    tmp_path: Path,
) -> None:
    """Regression (live check 2026-07-06): Gemini rejects pydantic's
    additionalProperties/title ANNOTATION keys in FunctionDeclaration
    parameters with HTTP 400 — while a PROPERTY literally named "title"
    (the event title field!) must survive. The cleaner therefore has to be
    structure-aware, and strictness is re-enforced by pydantic validation
    after the call, so nothing is lost."""
    from engine.agents.llm_function_call_mapper import function_declaration_schema

    def assert_clean(schema: object, path: str) -> None:
        """Walk SCHEMA nodes only — property-name maps are traversed by
        value, so a field called 'title' is not mistaken for an annotation."""
        if not isinstance(schema, dict):
            return
        for banned in ("additionalProperties", "title"):
            assert banned not in schema, f"annotation {banned!r} survived at {path}"
        for map_key in ("properties", "$defs"):
            names = schema.get(map_key)
            if isinstance(names, dict):
                for name, sub in names.items():
                    assert_clean(sub, f"{path}.{map_key}.{name}")
        assert_clean(schema.get("items"), f"{path}.items")
        for list_key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            entries = schema.get(list_key)
            if isinstance(entries, list):
                for i, item in enumerate(entries):
                    assert_clean(item, f"{path}.{list_key}[{i}]")

    registry = build_default_tool_registry(tmp_path)
    for card_type in CardType:
        tool = registry.tool_for_card_type(card_type.value)
        schema = function_declaration_schema(tool.params_model)
        assert schema["type"] == "object"  # still a real schema
        properties = schema["properties"]
        assert isinstance(properties, dict) and properties  # fields survived
        # every required name must exist in properties (the exact failure
        # mode Gemini 400'd on when the cleaner ate the 'title' property)
        required = schema.get("required", [])
        assert isinstance(required, list)
        for required_name in required:
            assert required_name in properties, f"{required_name} lost by cleaning"
        assert_clean(schema, tool.name)

    # The create_event params keep their literal "title" FIELD.
    event_schema = function_declaration_schema(
        registry.tool_for_card_type("create_event").params_model
    )
    event_properties = event_schema["properties"]
    assert isinstance(event_properties, dict) and "title" in event_properties
