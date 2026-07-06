"""OAuth desktop flow pure pieces + gateway parsing + free-slot arithmetic.

Fail-closed invariants under test: the PKCE challenge is the exact S256 of
the verifier; a state mismatch or consent denial aborts the flow; token
responses are validated hard; gateway responses missing required fields
raise typed errors; the Gmail draft MIME round-trips exactly; and the
free-slot computation is boundary-exact (a perfect fit counts, one minute
short does not).
"""

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from urllib.parse import parse_qs, urlparse

import pytest

from engine.agents.calendar_find_free_slot_tool import first_free_slot
from engine.google.dpapi_google_token_store import GoogleOAuthClientCredentials
from engine.google.google_api_gateway import (
    BusyInterval,
    build_draft_raw_mime,
    create_calendar_event,
    create_gmail_draft,
    create_google_contact,
    query_free_busy,
)
from engine.google.google_auth_errors import GoogleApiCallError, GoogleOAuthFlowError
from engine.google.oauth_desktop_flow import (
    GOOGLE_OAUTH_SCOPES,
    build_authorization_url,
    build_pkce_pair,
    parse_redirect_request_target,
    tokens_from_token_response,
)
from tests.agents_test_support import FakeGoogleSession

CREDS = GoogleOAuthClientCredentials("client-id-1", "client-secret-1")


# --- PKCE + authorization URL ---


def test_pkce_challenge_is_the_exact_s256_of_the_verifier() -> None:
    verifier, challenge = build_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert len(verifier) >= 43  # RFC 7636 minimum entropy


def test_pkce_pairs_are_unique_per_flow() -> None:
    assert build_pkce_pair() != build_pkce_pair()


def test_authorization_url_carries_exactly_the_pinned_parameters() -> None:
    url = build_authorization_url(
        CREDS,
        redirect_uri="http://127.0.0.1:51234/oauth2/callback",
        state="state-xyz",
        code_challenge="challenge-abc",
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["client-id-1"]
    assert query["redirect_uri"] == ["http://127.0.0.1:51234/oauth2/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [" ".join(GOOGLE_OAUTH_SCOPES)]
    assert query["state"] == ["state-xyz"]
    assert query["code_challenge"] == ["challenge-abc"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert "client_secret" not in query  # the secret never rides the URL


# --- redirect parsing (CSRF + denial, fail closed) ---


def test_redirect_with_matching_state_yields_the_code() -> None:
    target = "/oauth2/callback?state=s1&code=auth-code-42&scope=x"
    assert parse_redirect_request_target(target, expected_state="s1") == "auth-code-42"


@pytest.mark.parametrize(
    ("target", "match"),
    [
        ("/cb?state=WRONG&code=c", "state mismatch"),  # forged/replayed redirect
        ("/cb?code=c", "state mismatch"),  # state missing entirely
        ("/cb?state=s1&state=s1&code=c", "state mismatch"),  # duplicated state
        ("/cb?state=s1", "no authorization code"),
        ("/cb?state=s1&code=", "no authorization code"),
        ("/cb?state=s1&code=a&code=b", "no authorization code"),  # ambiguous
        ("/cb?error=access_denied&state=s1", "refused"),  # user said no
    ],
)
def test_bad_redirects_abort_the_flow(target: str, match: str) -> None:
    with pytest.raises(GoogleOAuthFlowError, match=match):
        parse_redirect_request_target(target, expected_state="s1")


# --- token response validation ---


def test_token_response_math_is_exact() -> None:
    tokens = tokens_from_token_response(
        {"access_token": "at", "refresh_token": "rt", "expires_in": 3599, "scope": "a b"},
        now_unix=1000.0,
    )
    assert tokens.expires_at_unix == 4599.0  # absolute clock, exact
    assert tokens.scopes == ("a", "b")


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"access_token": "", "refresh_token": "rt", "expires_in": 3600},
        {"access_token": "at", "expires_in": 3600},  # no refresh token, no carry
        {"access_token": "at", "refresh_token": "rt", "expires_in": 0},
        {"access_token": "at", "refresh_token": "rt", "expires_in": -5},
        {"access_token": "at", "refresh_token": "rt", "expires_in": True},  # bool!
        {"access_token": "at", "refresh_token": "rt"},
    ],
)
def test_malformed_token_responses_are_refused(response: dict[str, object]) -> None:
    with pytest.raises(GoogleOAuthFlowError):
        tokens_from_token_response(response, now_unix=1000.0)


def test_omitted_refresh_token_carries_the_existing_one_forward() -> None:
    tokens = tokens_from_token_response(
        {"access_token": "at", "expires_in": 3600},
        now_unix=0.0,
        existing_refresh_token="rt-old",  # noqa: S106 - synthetic fixture value
    )
    assert tokens.refresh_token == "rt-old"  # noqa: S105 - synthetic fixture value


# --- gateway request/response exactness (fake session, no network) ---


async def test_calendar_event_request_and_response_are_exact() -> None:
    session = FakeGoogleSession([{"id": "evt-1", "htmlLink": "https://cal/evt-1"}])
    created = await create_calendar_event(
        session,
        title="Contract review",
        start_iso="2026-07-10T13:00:00+00:00",
        end_iso="2026-07-10T14:00:00+00:00",
        description="Bring the redlines",
        attendee_emails=("tom@reed.io",),
    )
    assert created.event_id == "evt-1"
    method, url, body = session.requests[0]
    assert method == "POST"
    assert url.endswith("/calendars/primary/events")
    assert body == {
        "summary": "Contract review",
        "start": {"dateTime": "2026-07-10T13:00:00+00:00"},
        "end": {"dateTime": "2026-07-10T14:00:00+00:00"},
        "description": "Bring the redlines",
        "attendees": [{"email": "tom@reed.io"}],
    }


async def test_created_event_without_id_is_refused() -> None:
    session = FakeGoogleSession([{"htmlLink": "x"}])
    with pytest.raises(GoogleApiCallError, match="no id"):
        await create_calendar_event(
            session,
            title="t",
            start_iso="2026-07-10T13:00:00+00:00",
            end_iso="2026-07-10T14:00:00+00:00",
        )


async def test_free_busy_parses_and_one_bad_interval_poisons_the_answer() -> None:
    good = FakeGoogleSession(
        [{"calendars": {"primary": {"busy": [{"start": "s1", "end": "e1"}]}}}]
    )
    busy = await query_free_busy(
        good, time_min_iso="2026-07-10T09:00:00+00:00", time_max_iso="2026-07-10T18:00:00+00:00"
    )
    assert busy == (BusyInterval("s1", "e1"),)
    bad = FakeGoogleSession(
        [{"calendars": {"primary": {"busy": [{"start": "s1", "end": "e1"}, {"start": 5}]}}}]
    )
    with pytest.raises(GoogleApiCallError, match="malformed"):
        # A half-parsed busy list could double-book: refuse the whole answer.
        await query_free_busy(
            bad,
            time_min_iso="2026-07-10T09:00:00+00:00",
            time_max_iso="2026-07-10T18:00:00+00:00",
        )


async def test_contact_creation_without_resource_name_is_refused() -> None:
    session = FakeGoogleSession([{}])
    with pytest.raises(GoogleApiCallError, match="resourceName"):
        await create_google_contact(session, name="Ana Cruz")


async def test_gmail_draft_round_trips_the_mime_exactly() -> None:
    session = FakeGoogleSession([{"id": "draft-1", "message": {"id": "msg-1"}}])
    created = await create_gmail_draft(
        session, to=("tom@reed.io", "ana@cruz.io"), subject="Terms", body_text="Hi both,\nDraft."
    )
    assert created.draft_id == "draft-1" and created.message_id == "msg-1"
    _, url, body = session.requests[0]
    assert url.endswith("/users/me/drafts")
    assert isinstance(body, dict)
    message = body["message"]
    assert isinstance(message, dict) and set(message) == {"raw"}  # a draft, nothing else
    decoded = message_from_bytes(base64.urlsafe_b64decode(str(message["raw"])))
    assert decoded["To"] == "tom@reed.io, ana@cruz.io"
    assert decoded["Subject"] == "Terms"
    body_text = decoded.get_payload()
    assert isinstance(body_text, str) and body_text.strip() == "Hi both,\nDraft."


def test_draft_mime_without_recipients_has_no_to_header() -> None:
    decoded = message_from_bytes(base64.urlsafe_b64decode(build_draft_raw_mime((), "S", "B")))
    assert decoded["To"] is None
    assert decoded["Subject"] == "S"


# --- free-slot arithmetic (pure, boundary-exact) ---

_T0 = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)


def _busy(start_h: float, end_h: float) -> BusyInterval:
    return BusyInterval(
        (_T0 + timedelta(hours=start_h)).isoformat(),
        (_T0 + timedelta(hours=end_h)).isoformat(),
    )


def test_empty_calendar_yields_the_window_start() -> None:
    slot = first_free_slot(
        (), window_start=_T0, window_end=_T0 + timedelta(hours=9),
        duration=timedelta(minutes=60),
    )
    assert slot == (_T0, _T0 + timedelta(minutes=60))


def test_exact_fit_gap_counts_and_one_minute_short_does_not() -> None:
    """Boundary-exact: a 60-min gap fits a 60-min meeting; 59 does not."""
    busy_exact = (_busy(0, 1), _busy(2, 3))  # gap 10:00-11:00 == 60 min
    slot = first_free_slot(
        busy_exact, window_start=_T0, window_end=_T0 + timedelta(hours=3),
        duration=timedelta(minutes=60),
    )
    assert slot == (_T0 + timedelta(hours=1), _T0 + timedelta(hours=2))
    busy_short = (_busy(0, 1), _busy(1.9833333333333334, 3))  # gap = 59 min
    slot_short = first_free_slot(
        busy_short, window_start=_T0, window_end=_T0 + timedelta(hours=3),
        duration=timedelta(minutes=60),
    )
    assert slot_short is None  # no squeezing, no overlap, honest none


def test_overlapping_and_unordered_busy_intervals_merge_correctly() -> None:
    busy = (_busy(3, 5), _busy(0, 2), _busy(1, 4))  # unordered + overlapping
    slot = first_free_slot(
        busy, window_start=_T0, window_end=_T0 + timedelta(hours=9),
        duration=timedelta(minutes=30),
    )
    assert slot == (_T0 + timedelta(hours=5), _T0 + timedelta(hours=5, minutes=30))


def test_busy_outside_the_window_is_ignored() -> None:
    busy = (_busy(-5, -2), _busy(12, 15))
    slot = first_free_slot(
        busy, window_start=_T0, window_end=_T0 + timedelta(hours=1),
        duration=timedelta(minutes=60),
    )
    assert slot == (_T0, _T0 + timedelta(hours=1))


def test_fully_booked_window_yields_none() -> None:
    slot = first_free_slot(
        (_busy(0, 9),), window_start=_T0, window_end=_T0 + timedelta(hours=9),
        duration=timedelta(minutes=1),
    )
    assert slot is None
