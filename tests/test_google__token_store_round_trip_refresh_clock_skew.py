"""Google token custody: DPAPI round-trip, refresh flow, clock-skew boundary.

Invariants under test (claude.md §5.6): tokens round-trip through the
DPAPI blob byte-exact and never appear in reprs; a tampered blob raises
(fail closed) rather than reading as "not connected"; the skew boundary
is EXACT (refresh at now >= expires_at - 300, not a second sooner); a
missing token set is a typed ``GoogleNotConnectedError``; a failed refresh
is a typed ``GoogleTokenRefreshError`` that leaves the store unchanged.

DPAPI is real on this Windows box — the round-trip exercises the actual
CryptProtectData path, per-user.
"""

from pathlib import Path

import pytest

from engine.google.dpapi_google_token_store import (
    CLOCK_SKEW_TOLERANCE_SECONDS,
    GoogleOAuthClientCredentials,
    GoogleOAuthTokens,
    GoogleTokenStore,
)
from engine.google.google_auth_errors import (
    GoogleNotConnectedError,
    GoogleTokenRefreshError,
)
from engine.google.google_session import DpapiGoogleSession

NOW = 1_800_000_000.0


def _tokens(expires_at: float = NOW + 3600.0) -> GoogleOAuthTokens:
    return GoogleOAuthTokens(
        access_token="ya29.test-access",  # noqa: S106 - synthetic fixture value
        refresh_token="1//test-refresh",  # noqa: S106 - synthetic fixture value
        expires_at_unix=expires_at,
        scopes=("scope-a", "scope-b"),
    )


def _store(tmp_path: Path) -> GoogleTokenStore:
    return GoogleTokenStore(tmp_path / "google_tokens.bin")


def test_round_trip_is_exact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_tokens(_tokens())
    loaded = store.load_tokens()
    assert loaded == _tokens()  # every field, exactly


def test_missing_file_reads_as_not_connected(tmp_path: Path) -> None:
    assert _store(tmp_path).load_tokens() is None


def test_blob_on_disk_is_ciphertext_not_plaintext(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_tokens(_tokens())
    raw = (tmp_path / "google_tokens.bin").read_bytes()
    assert b"ya29.test-access" not in raw  # plaintext never touches disk
    assert b"1//test-refresh" not in raw


def test_tampered_blob_raises_instead_of_reading_empty(tmp_path: Path) -> None:
    """Fail closed: corruption is an error, never silently 'not connected'."""
    store = _store(tmp_path)
    store.save_tokens(_tokens())
    blob_path = tmp_path / "google_tokens.bin"
    blob_path.write_bytes(b"\x00\x01tampered" + blob_path.read_bytes()[10:])
    with pytest.raises(Exception):  # noqa: B017 - DPAPI error class is OS-defined
        store.load_tokens()


def test_client_credentials_round_trip_and_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    assert store.load_client_credentials() is None
    # env fallback (dev mode)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "env-secret")
    creds = store.load_client_credentials()
    assert creds == GoogleOAuthClientCredentials("env-id", "env-secret")
    # stored credentials beat the environment (user's deliberate save wins)
    store.save_client_credentials(GoogleOAuthClientCredentials("stored-id", "stored-secret"))
    stored = store.load_client_credentials()
    assert stored is not None and stored.client_id == "stored-id"
    # saving tokens preserves client credentials in the same blob
    store.save_tokens(_tokens())
    still = store.load_client_credentials()
    assert still is not None and still.client_id == "stored-id"


def test_no_token_material_in_reprs() -> None:
    tokens = _tokens()
    creds = GoogleOAuthClientCredentials("id-ok-to-show", "super-secret-value")
    assert "ya29.test-access" not in repr(tokens)
    assert "1//test-refresh" not in repr(tokens)
    assert "super-secret-value" not in repr(creds)


# --- clock-skew boundary (exact to the second) ---


def test_expiring_soon_boundary_is_exact() -> None:
    """Refresh triggers at now == expires_at - skew (on), not one second
    before (just-under): boundary-exact per §3.6."""
    tokens = _tokens(expires_at=NOW + CLOCK_SKEW_TOLERANCE_SECONDS)
    assert tokens.expiring_soon(NOW) is True  # exactly on the boundary: refresh
    assert tokens.expiring_soon(NOW - 1.0) is False  # one second earlier: keep
    assert tokens.expiring_soon(NOW + 1.0) is True  # past it: refresh


# --- session refresh flow (fake transport; no network) ---


async def test_session_refreshes_inside_skew_window_and_persists(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save_client_credentials(GoogleOAuthClientCredentials("cid", "csec"))
    store.save_tokens(_tokens(expires_at=NOW + 10.0))  # inside the 300s window
    posted: list[dict[str, str]] = []

    async def fake_post(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        posted.append(form)
        return {"access_token": "ya29.refreshed", "expires_in": 3600}

    session = DpapiGoogleSession(store, token_refresh_post=fake_post, clock=lambda: NOW)
    token = await session._fresh_access_token()
    assert token == "ya29.refreshed"  # noqa: S105 - synthetic fixture value
    assert posted[0]["grant_type"] == "refresh_token"
    assert posted[0]["refresh_token"] == "1//test-refresh"  # noqa: S105 - synthetic fixture
    persisted = store.load_tokens()
    assert persisted is not None
    assert persisted.access_token == "ya29.refreshed"  # noqa: S105 - synthetic fixture value
    assert persisted.expires_at_unix == NOW + 3600.0  # absolute-clock arithmetic
    # Google omitted the refresh token: the existing one is carried forward.
    assert persisted.refresh_token == "1//test-refresh"  # noqa: S105 - synthetic fixture value


async def test_session_does_not_refresh_outside_the_window(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_tokens(_tokens(expires_at=NOW + CLOCK_SKEW_TOLERANCE_SECONDS + 1.0))

    async def must_not_post(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        raise AssertionError("refresh must not run outside the skew window")

    session = DpapiGoogleSession(store, token_refresh_post=must_not_post, clock=lambda: NOW)
    assert await session._fresh_access_token() == "ya29.test-access"


async def test_no_tokens_is_a_typed_not_connected_error(tmp_path: Path) -> None:
    session = DpapiGoogleSession(_store(tmp_path), clock=lambda: NOW)
    with pytest.raises(GoogleNotConnectedError, match="not connected"):
        await session._fresh_access_token()


async def test_failed_refresh_is_typed_and_leaves_the_store_unchanged(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save_client_credentials(GoogleOAuthClientCredentials("cid", "csec"))
    original = _tokens(expires_at=NOW - 100.0)  # already expired
    store.save_tokens(original)

    async def broken_post(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        raise RuntimeError("refresh endpoint on fire (with a secret inside)")

    session = DpapiGoogleSession(store, token_refresh_post=broken_post, clock=lambda: NOW)
    with pytest.raises(GoogleTokenRefreshError) as excinfo:
        await session._fresh_access_token()
    # Redaction: the transport's message (which could echo secrets) is NOT
    # propagated — only the failure class name is.
    assert "on fire" not in str(excinfo.value)
    assert store.load_tokens() == original  # nothing was clobbered


async def test_malformed_refresh_response_is_typed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_client_credentials(GoogleOAuthClientCredentials("cid", "csec"))
    store.save_tokens(_tokens(expires_at=NOW))

    async def junk_post(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        return {"nothing": "useful"}

    session = DpapiGoogleSession(store, token_refresh_post=junk_post, clock=lambda: NOW)
    with pytest.raises(GoogleTokenRefreshError, match="invalid"):
        await session._fresh_access_token()
