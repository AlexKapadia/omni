"""Adversarial coverage of the OAuth desktop flow + authorised session edges.

Everything here asserts CORRECT behaviour and fails if the code were wrong:
- the loopback redirect handler extracts the exact request target and writes
  a real 200 response;
- the whole desktop flow, driven end-to-end over a real in-process 127.0.0.1
  loopback (NOT faked — the socket bind is exercised for real, locally, with
  no egress), mints and persists exactly the tokens the exchange returned,
  fails closed on a missing timeout redirect, and refuses without credentials;
- the lazily-imported httpx transports (token exchange, refresh, authorised
  request) map every status/shape branch to the right typed error and NEVER
  echo secrets or bodies. httpx is monkeypatched at ``httpx.AsyncClient`` so no
  bytes leave the machine.

Fakes only (claude.md §5.5): a subclassed token store (no disk for the flow),
a fake httpx client, and injected exchange/refresh callables.
"""

import asyncio
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from engine.google.dpapi_google_token_store import (
    GoogleOAuthClientCredentials,
    GoogleOAuthTokens,
    GoogleTokenStore,
)
from engine.google.google_auth_errors import (
    GoogleApiCallError,
    GoogleDependencyMissingError,
    GoogleOAuthFlowError,
    GoogleTokenRefreshError,
)
from engine.google.google_session import (
    DpapiGoogleSession,
    GoogleSession,
    _default_form_post,
)
from engine.google.oauth_desktop_flow import (
    GOOGLE_TOKEN_ENDPOINT,
    _default_token_exchange,
    _OneShotRedirectServer,
    run_google_oauth_desktop_flow,
)

NOW = 1_800_000_000.0


# --------------------------------------------------------------------------
# Fake httpx transport (monkeypatched onto httpx.AsyncClient in each test).
# --------------------------------------------------------------------------


class _FakeResp:
    """A minimal httpx-shaped response: status + a json() that can also blow up."""

    def __init__(
        self, status_code: int, json_value: object = None, *, raise_json: bool = False
    ) -> None:
        self.status_code = status_code
        self._json_value = json_value
        self._raise_json = raise_json

    def json(self) -> object:
        if self._raise_json:
            raise ValueError("response body is not JSON")
        return self._json_value


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: _FakeResp | None = None,
    error: Exception | None = None,
    record: list[object] | None = None,
) -> None:
    """Replace httpx.AsyncClient with a fake that returns ``response`` (or raises
    ``error``) and records outgoing calls into ``record``."""

    class _FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, endpoint: str, data: object = None) -> _FakeResp:
            if record is not None:
                record.append(("POST", endpoint, data))
            if error is not None:
                raise error
            assert response is not None
            return response

        async def request(
            self,
            method: str,
            url: str,
            *,
            params: object = None,
            json: object = None,
            headers: object = None,
        ) -> _FakeResp:
            if record is not None:
                record.append((method, url, params, json, headers))
            if error is not None:
                raise error
            assert response is not None
            return response

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


# --------------------------------------------------------------------------
# Loopback redirect handler (pure StreamReader/StreamWriter contract).
# --------------------------------------------------------------------------


class _FakeReader:
    def __init__(self, line: bytes) -> None:
        self._line = line

    async def readline(self) -> bytes:
        return self._line


class _FakeWriter:
    def __init__(self) -> None:
        self.written = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


async def test_redirect_handler_extracts_target_and_writes_200() -> None:
    server = _OneShotRedirectServer()
    writer = _FakeWriter()
    await server.handle(
        _FakeReader(b"GET /oauth2/callback?state=s1&code=c1 HTTP/1.1\r\n"),  # type: ignore[arg-type]
        writer,  # type: ignore[arg-type]
    )
    assert server.target_future.result() == "/oauth2/callback?state=s1&code=c1"
    assert b"200 OK" in writer.written  # a real HTTP response was served
    assert writer.closed  # the one-shot connection is always closed


async def test_redirect_handler_defaults_target_on_malformed_request_line() -> None:
    """A request line with no space (no method/target split) falls back to '/'
    rather than crashing — then downstream state validation fails closed."""
    server = _OneShotRedirectServer()
    await server.handle(_FakeReader(b"garbage\r\n"), _FakeWriter())  # type: ignore[arg-type]
    assert server.target_future.result() == "/"


# --------------------------------------------------------------------------
# Full desktop flow over a REAL in-process loopback socket.
# --------------------------------------------------------------------------


class _FlowStore(GoogleTokenStore):
    """Store stub for the flow: canned credentials, records the saved tokens.
    Subclasses the real type so the flow's static contract still holds; the two
    overridden methods are the only ones the flow touches, so no disk is used."""

    def __init__(self, credentials: GoogleOAuthClientCredentials | None) -> None:
        self._credentials = credentials
        self.saved: GoogleOAuthTokens | None = None

    def load_client_credentials(self) -> GoogleOAuthClientCredentials | None:
        return self._credentials

    def save_tokens(self, tokens: GoogleOAuthTokens) -> None:
        self.saved = tokens


def _loopback_open_browser(
    code: str, tasks: list["asyncio.Task[None]"]
) -> Callable[[str], object]:
    """A browser stub that, instead of opening a browser, replays Google's
    redirect back to the flow's loopback listener with a matching state."""

    def open_browser(url: str) -> None:
        query = parse_qs(urlparse(url).query)
        state = query["state"][0]  # echo the flow's own state (CSRF ok)
        port = urlparse(query["redirect_uri"][0]).port
        assert port is not None

        async def _replay() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            request = (
                f"GET /oauth2/callback?state={state}&code={code} "
                "HTTP/1.1\r\nHost: localhost\r\n\r\n"
            )
            writer.write(request.encode("latin-1"))
            await writer.drain()
            await reader.read()  # keep the socket up until the server drains
            writer.close()

        tasks.append(asyncio.ensure_future(_replay()))

    return open_browser


async def test_full_desktop_flow_persists_exactly_the_exchanged_tokens() -> None:
    store = _FlowStore(GoogleOAuthClientCredentials("cid", "csec"))
    tasks: list[asyncio.Task[None]] = []
    seen_form: dict[str, str] = {}

    async def fake_exchange(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        seen_form.update(form)
        return {
            "access_token": "at-new",
            "refresh_token": "rt-new",
            "expires_in": 3600,
        }

    tokens = await run_google_oauth_desktop_flow(
        store,
        open_browser=_loopback_open_browser("auth-code-xyz", tasks),
        token_exchange=fake_exchange,
        timeout_seconds=5.0,
    )
    await asyncio.gather(*tasks)

    # The exchange got the authorization-code grant with the exact code + PKCE.
    assert seen_form["grant_type"] == "authorization_code"
    assert seen_form["code"] == "auth-code-xyz"
    assert seen_form["client_id"] == "cid"
    assert seen_form["client_secret"] == "csec"  # noqa: S105 - synthetic fixture value
    assert seen_form["code_verifier"]  # PKCE verifier accompanies the exchange
    assert seen_form["redirect_uri"].startswith("http://127.0.0.1:")
    # The returned tokens are exactly what was persisted (same object).
    assert tokens.access_token == "at-new"  # noqa: S105 - synthetic
    assert tokens.refresh_token == "rt-new"  # noqa: S105 - synthetic
    assert store.saved is tokens


async def test_full_desktop_flow_times_out_and_saves_nothing() -> None:
    store = _FlowStore(GoogleOAuthClientCredentials("cid", "csec"))

    def never_redirects(url: str) -> None:
        return None

    async def unused_exchange(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        raise AssertionError("exchange must not run when the redirect never arrives")

    with pytest.raises(GoogleOAuthFlowError, match="timed out"):
        await run_google_oauth_desktop_flow(
            store,
            open_browser=never_redirects,
            token_exchange=unused_exchange,
            timeout_seconds=0.05,
        )
    assert store.saved is None  # fail closed: no tokens on a failed flow


async def test_flow_without_client_credentials_fails_closed() -> None:
    async def unused_exchange(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        raise AssertionError("no credentials means the flow never reaches exchange")

    with pytest.raises(GoogleOAuthFlowError, match="client credentials"):
        await run_google_oauth_desktop_flow(
            _FlowStore(None),
            open_browser=lambda _url: None,
            token_exchange=unused_exchange,
        )


# --------------------------------------------------------------------------
# _default_token_exchange (httpx path).
# --------------------------------------------------------------------------


async def test_default_token_exchange_returns_the_decoded_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, {"access_token": "at"}))
    out = await _default_token_exchange(GOOGLE_TOKEN_ENDPOINT, {"grant_type": "x"})
    assert out == {"access_token": "at"}


async def test_default_token_exchange_non_200_is_typed_and_body_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(400, {"error": "invalid_grant"}))
    with pytest.raises(GoogleOAuthFlowError) as excinfo:
        await _default_token_exchange(GOOGLE_TOKEN_ENDPOINT, {"client_secret": "s3cr3t"})
    message = str(excinfo.value)
    assert "HTTP 400" in message
    assert "s3cr3t" not in message  # the client secret never rides the error
    assert "invalid_grant" not in message  # nor the response body


async def test_default_token_exchange_non_object_body_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, ["not", "an", "object"]))
    with pytest.raises(GoogleOAuthFlowError, match="non-object"):
        await _default_token_exchange(GOOGLE_TOKEN_ENDPOINT, {})


# --------------------------------------------------------------------------
# Session: base contract + refresh edges.
# --------------------------------------------------------------------------


async def test_base_session_request_json_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await GoogleSession().request_json("GET", "https://api.example")


def _store(tmp_path_bin: object) -> GoogleTokenStore:
    from pathlib import Path

    assert isinstance(tmp_path_bin, Path)
    return GoogleTokenStore(tmp_path_bin / "google_tokens.bin")


def _expiring_tokens() -> GoogleOAuthTokens:
    return GoogleOAuthTokens(
        access_token="at-old",  # noqa: S106 - synthetic
        refresh_token="rt-old",  # noqa: S106 - synthetic
        expires_at_unix=NOW,  # now == expiry -> inside skew window, refresh
        scopes=("s",),
    )


async def test_refresh_without_client_credentials_is_typed(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    store = _store(tmp_path)
    store.save_tokens(_expiring_tokens())
    session = DpapiGoogleSession(store, clock=lambda: NOW)
    with pytest.raises(GoogleTokenRefreshError, match="credentials are missing"):
        await session._fresh_access_token()


async def test_refresh_propagates_dependency_missing_unwrapped(tmp_path: object) -> None:
    """A missing httpx during refresh surfaces as the dependency error itself,
    NOT re-wrapped as a generic refresh failure (so the UI can name the cause)."""
    store = _store(tmp_path)
    store.save_client_credentials(GoogleOAuthClientCredentials("cid", "csec"))
    store.save_tokens(_expiring_tokens())

    async def dep_missing(endpoint: str, form: dict[str, str]) -> dict[str, object]:
        raise GoogleDependencyMissingError("httpx")

    session = DpapiGoogleSession(store, token_refresh_post=dep_missing, clock=lambda: NOW)
    with pytest.raises(GoogleDependencyMissingError):
        await session._fresh_access_token()


# --------------------------------------------------------------------------
# Session.request_json (httpx path) — every status/shape branch.
# --------------------------------------------------------------------------


def _fresh_session(tmp_path_bin: object) -> DpapiGoogleSession:
    store = _store(tmp_path_bin)
    store.save_tokens(
        GoogleOAuthTokens(
            access_token="at-fresh",  # noqa: S106 - synthetic
            refresh_token="rt",  # noqa: S106 - synthetic
            expires_at_unix=NOW + 10_000.0,  # far from expiry -> no refresh
            scopes=("s",),
        )
    )
    return DpapiGoogleSession(store, clock=lambda: NOW)


async def test_request_json_sends_bearer_and_returns_object(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    record: list[object] = []
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, {"ok": True}), record=record)
    session = _fresh_session(tmp_path)
    out = await session.request_json(
        "PATCH", "https://api.example", params={"a": "b"}, json_body={"x": 1}
    )
    assert out == {"ok": True}
    entry = record[0]
    assert isinstance(entry, tuple)
    method, url, params, json_body, headers = entry
    assert method == "PATCH" and url == "https://api.example"
    assert params == {"a": "b"} and json_body == {"x": 1}
    # The stored access token is placed on Authorization exactly once, verbatim.
    assert headers == {"Authorization": "Bearer at-fresh"}


async def test_request_json_non_2xx_is_typed_with_status(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(503, {"huge": "body"}))
    session = _fresh_session(tmp_path)
    with pytest.raises(GoogleApiCallError) as excinfo:
        await session.request_json("GET", "https://api.example")
    assert excinfo.value.status_code == 503  # exact status surfaced
    assert "body" not in str(excinfo.value)  # the response body is never echoed


async def test_request_json_transport_error_is_typed_and_redacted(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(monkeypatch, error=httpx.HTTPError("secret in the message"))
    session = _fresh_session(tmp_path)
    with pytest.raises(GoogleApiCallError) as excinfo:
        await session.request_json("GET", "https://api.example")
    assert excinfo.value.status_code is None  # no HTTP response was received
    assert "secret in the message" not in str(excinfo.value)  # only the class name


async def test_request_json_non_json_body_is_typed(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, raise_json=True))
    session = _fresh_session(tmp_path)
    with pytest.raises(GoogleApiCallError, match="non-JSON"):
        await session.request_json("GET", "https://api.example")


async def test_request_json_non_object_body_is_typed(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, [1, 2, 3]))
    session = _fresh_session(tmp_path)
    with pytest.raises(GoogleApiCallError, match="non-object"):
        await session.request_json("GET", "https://api.example")


# --------------------------------------------------------------------------
# _default_form_post (refresh transport, httpx path).
# --------------------------------------------------------------------------


async def test_default_form_post_returns_the_decoded_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, {"access_token": "a"}))
    out = await _default_form_post(GOOGLE_TOKEN_ENDPOINT, {"grant_type": "refresh_token"})
    assert out == {"access_token": "a"}


async def test_default_form_post_non_200_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(401, {}))
    with pytest.raises(GoogleTokenRefreshError, match="HTTP 401"):
        await _default_form_post(GOOGLE_TOKEN_ENDPOINT, {})


async def test_default_form_post_non_object_body_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch, response=_FakeResp(200, "a string, not an object"))
    with pytest.raises(GoogleTokenRefreshError, match="non-object"):
        await _default_form_post(GOOGLE_TOKEN_ENDPOINT, {})
