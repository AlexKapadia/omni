"""Adversarial coverage of gateway response branches + token-store edges.

Everything asserts CORRECT, fail-closed behaviour:
- freeBusy parsing refuses a missing ``calendars`` map, a missing requested
  calendar, and a non-list ``busy`` (any of which could silently hide busy
  time and double-book);
- a contact request carries every optional field in the exact People wire
  shape, and a draft with no id is refused (a missing message id degrades to
  an empty string, never a crash);
- the DPAPI token store reads a shape-mangled blob as "not connected" (only
  because the codec itself succeeded), rejects a non-object blob, and
  ``clear_tokens`` drops tokens while preserving client credentials.

The real Windows DPAPI syscall is replaced by an injected passthrough codec
(claude.md §5.5) so blob SHAPES can be crafted deterministically; the real
CryptProtectData round-trip is covered in the sibling token-store test file.
"""

import json
from pathlib import Path

import pytest

import engine.google.dpapi_google_token_store as token_store_module
from engine.google.dpapi_google_token_store import (
    GoogleOAuthClientCredentials,
    GoogleOAuthTokens,
    GoogleTokenStore,
)
from engine.google.google_api_gateway import (
    PEOPLE_CREATE_CONTACT_URL,
    create_gmail_draft,
    create_google_contact,
    query_free_busy,
)
from engine.google.google_auth_errors import GoogleApiCallError
from tests.agents_test_support import FakeGoogleSession

WINDOW = {"time_min_iso": "2026-07-10T09:00:00+00:00", "time_max_iso": "2026-07-10T18:00:00+00:00"}


# --------------------------------------------------------------------------
# Gateway: freeBusy fail-closed parsing branches.
# --------------------------------------------------------------------------


async def test_free_busy_refuses_when_calendars_is_not_a_map() -> None:
    session = FakeGoogleSession([{"calendars": "not-a-map"}])
    with pytest.raises(GoogleApiCallError, match="no calendars"):
        await query_free_busy(session, **WINDOW)


async def test_free_busy_refuses_when_requested_calendar_is_absent() -> None:
    session = FakeGoogleSession([{"calendars": {"someone-elses": {"busy": []}}}])
    with pytest.raises(GoogleApiCallError, match="missing from response"):
        await query_free_busy(session, **WINDOW)  # default calendar_id 'primary' absent


async def test_free_busy_refuses_when_busy_is_not_a_list() -> None:
    session = FakeGoogleSession([{"calendars": {"primary": {"busy": {"start": "s"}}}}])
    with pytest.raises(GoogleApiCallError, match="busy list malformed"):
        await query_free_busy(session, **WINDOW)


async def test_free_busy_with_absent_busy_key_is_an_empty_answer() -> None:
    """A calendar entry with no ``busy`` key is a legitimately free calendar —
    the default is an empty list, not an error."""
    session = FakeGoogleSession([{"calendars": {"primary": {}}}])
    assert await query_free_busy(session, **WINDOW) == ()


# --------------------------------------------------------------------------
# Gateway: contact optional-field wiring + draft id edges.
# --------------------------------------------------------------------------


async def test_contact_serialises_every_optional_field_exactly() -> None:
    session = FakeGoogleSession([{"resourceName": "people/c123"}])
    created = await create_google_contact(
        session,
        name="Ana Cruz",
        email="ana@cruz.io",
        phone="+1-555-0100",
        company="Reed & Co",
    )
    assert created.resource_name == "people/c123"
    method, url, body = session.requests[0]
    assert method == "POST" and url == PEOPLE_CREATE_CONTACT_URL
    # Exact People wire shape — each optional field lands in its own key.
    assert body == {
        "names": [{"unstructuredName": "Ana Cruz"}],
        "emailAddresses": [{"value": "ana@cruz.io"}],
        "phoneNumbers": [{"value": "+1-555-0100"}],
        "organizations": [{"name": "Reed & Co"}],
    }


async def test_contact_omits_optional_fields_when_not_given() -> None:
    session = FakeGoogleSession([{"resourceName": "people/c1"}])
    await create_google_contact(session, name="Just Name")
    _, _, body = session.requests[0]
    assert body == {"names": [{"unstructuredName": "Just Name"}]}  # nothing invented


async def test_gmail_draft_without_id_is_refused() -> None:
    session = FakeGoogleSession([{"message": {"id": "msg-1"}}])  # draft id missing
    with pytest.raises(GoogleApiCallError, match="no id"):
        await create_gmail_draft(session, to=("a@b.io",), subject="S", body_text="B")


async def test_gmail_draft_without_message_object_yields_empty_message_id() -> None:
    session = FakeGoogleSession([{"id": "draft-9"}])  # id present, message absent
    created = await create_gmail_draft(session, to=(), subject="S", body_text="B")
    assert created.draft_id == "draft-9"
    assert created.message_id == ""  # missing message degrades, never crashes


# --------------------------------------------------------------------------
# Token store: shape-mangled / non-object blobs + clear_tokens.
# --------------------------------------------------------------------------


def _passthrough_codec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the real DPAPI codec for identity so blob SHAPES are craftable.
    (Encryption-at-rest is proven with the REAL codec in the sibling file.)"""
    monkeypatch.setattr(token_store_module, "dpapi_protect", lambda plaintext: plaintext)
    monkeypatch.setattr(token_store_module, "dpapi_unprotect", lambda ciphertext: ciphertext)


@pytest.mark.parametrize(
    "tokens_value",
    [
        {"access_token": "a"},  # missing refresh_token / expires_at -> KeyError
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_at_unix": "not-a-number",  # -> ValueError on float()
        },
    ],
)
def test_shape_mangled_tokens_read_as_not_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tokens_value: dict[str, object]
) -> None:
    """A decoder-successful-but-shape-broken token map reads as 'not connected'
    (None) — NOT a crash, and NOT a half-populated token set."""
    _passthrough_codec(monkeypatch)
    blob_path = tmp_path / "google_tokens.bin"
    blob_path.write_bytes(json.dumps({"tokens": tokens_value}).encode("utf-8"))
    assert GoogleTokenStore(blob_path).load_tokens() is None


def test_non_object_blob_is_rejected_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JSON array (not an object) at the top level is corruption, not empty —
    it raises rather than silently reading as 'not connected'."""
    _passthrough_codec(monkeypatch)
    blob_path = tmp_path / "google_tokens.bin"
    blob_path.write_bytes(json.dumps([1, 2, 3]).encode("utf-8"))
    with pytest.raises(ValueError, match="not a JSON object"):
        GoogleTokenStore(blob_path).load_tokens()


def test_clear_tokens_drops_tokens_but_keeps_client_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _passthrough_codec(monkeypatch)
    store = GoogleTokenStore(tmp_path / "google_tokens.bin")
    store.save_client_credentials(GoogleOAuthClientCredentials("cid", "csec"))
    store.save_tokens(
        GoogleOAuthTokens(
            access_token="at",  # noqa: S106 - synthetic
            refresh_token="rt",  # noqa: S106 - synthetic
            expires_at_unix=1.0,
        )
    )
    assert store.load_tokens() is not None

    store.clear_tokens()
    assert store.load_tokens() is None  # tokens dropped
    creds = store.load_client_credentials()
    assert creds is not None and creds.client_id == "cid"  # credentials survive disconnect


def test_clear_tokens_is_a_noop_when_already_disconnected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """clear_tokens on a store that holds no tokens must not error and must not
    rewrite the blob (the 'tokens in blob' guard)."""
    _passthrough_codec(monkeypatch)
    store = GoogleTokenStore(tmp_path / "google_tokens.bin")
    store.save_client_credentials(GoogleOAuthClientCredentials("cid", "csec"))
    store.clear_tokens()  # no tokens present -> guarded skip, no crash
    assert store.load_tokens() is None
    creds = store.load_client_credentials()
    assert creds is not None and creds.client_id == "cid"
