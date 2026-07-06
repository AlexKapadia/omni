"""Google OAuth 2.0 desktop (loopback) flow with PKCE.

Purpose: connect the user's Google account without embedding any web
service — open the system browser at Google's consent screen, catch the
single redirect on a 127.0.0.1 loopback listener, exchange the code for
tokens, and hand them to the DPAPI store. Code-complete and fail-closed;
runnable the moment the user pastes OAuth client credentials (none exist
on this box yet — tests drive the pure pieces and a fake exchange).
Pipeline position: invoked from Settings/onboarding (deferred server
wiring); ``google_session`` consumes the stored tokens afterwards.

Security invariants:
- SCOPES ARE PINNED to exactly three: calendar events, contacts, and Gmail
  draft composition. Nothing wider is ever requested; the registry/gateway
  additionally expose NO send capability at all (draft-only, binding).
- PKCE (S256) + a random ``state`` checked on the redirect (CSRF defence);
  a state mismatch aborts the flow (fail closed).
- The loopback listener binds 127.0.0.1 only and accepts exactly one
  request; tokens/secrets never appear in logs or error messages.
"""

import asyncio
import base64
import hashlib
import secrets
import time
import webbrowser
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, quote, urlparse

from engine.google.dpapi_google_token_store import (
    GoogleOAuthClientCredentials,
    GoogleOAuthTokens,
    GoogleTokenStore,
)
from engine.google.google_auth_errors import GoogleOAuthFlowError

# Pinned Google endpoints (OAuth 2.0 for desktop apps).
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 — a URL, not a secret

# SCOPE PIN (binding): exactly these three, nothing more. gmail.compose
# covers draft creation; the engine's gateway deliberately implements no
# message-dispatch endpoint on top of it (draft-only invariant lives in code
# AND is asserted by tests that scan these sources).
GOOGLE_OAUTH_SCOPES: tuple[str, str, str] = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/gmail.compose",
)

# Injectable token-exchange transport: (endpoint, form_fields) -> response
# dict. The default lazily imports httpx; tests inject a fake.
TokenExchangeTransport = Callable[[str, dict[str, str]], Awaitable[dict[str, object]]]


def build_pkce_pair() -> tuple[str, str]:
    """A fresh (code_verifier, S256 code_challenge) pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    credentials: GoogleOAuthClientCredentials,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    """The exact consent-screen URL for this flow (offline access for a
    refresh token; PKCE S256; pinned scopes)."""
    scope = quote(" ".join(GOOGLE_OAUTH_SCOPES), safe="")
    return (
        f"{GOOGLE_AUTHORIZATION_ENDPOINT}"
        f"?client_id={quote(credentials.client_id, safe='')}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        "&response_type=code"
        f"&scope={scope}"
        f"&state={quote(state, safe='')}"
        f"&code_challenge={quote(code_challenge, safe='')}"
        "&code_challenge_method=S256"
        "&access_type=offline"
        "&prompt=consent"
    )


def parse_redirect_request_target(target: str, *, expected_state: str) -> str:
    """Extract the authorization code from the loopback GET target.

    Fail closed: a consent denial, a missing code, or a state mismatch
    (CSRF defence) all raise :class:`GoogleOAuthFlowError`.
    """
    query = parse_qs(urlparse(target).query)
    if "error" in query:
        raise GoogleOAuthFlowError(f"Google refused the request: {query['error'][0]}")
    states = query.get("state", [])
    if states != [expected_state]:
        # fail-closed: a forged/replayed redirect must never mint tokens.
        raise GoogleOAuthFlowError("state mismatch on the OAuth redirect — flow aborted")
    codes = query.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise GoogleOAuthFlowError("no authorization code on the OAuth redirect")
    return codes[0]


def tokens_from_token_response(
    response: dict[str, object], *, now_unix: float, existing_refresh_token: str | None = None
) -> GoogleOAuthTokens:
    """Validate a token-endpoint response into a stored token set.

    ``expires_at_unix`` is computed from the ABSOLUTE clock at receipt, so
    the skew tolerance in the store works across restarts. Google omits the
    refresh token on re-consent — an existing one is carried forward.
    """
    access_token = response.get("access_token")
    expires_in = response.get("expires_in")
    refresh_token = response.get("refresh_token", existing_refresh_token)
    if not isinstance(access_token, str) or not access_token:
        raise GoogleOAuthFlowError("token response carried no access token")
    if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0:
        raise GoogleOAuthFlowError("token response carried no usable expiry")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise GoogleOAuthFlowError("token response carried no refresh token")
    scopes_raw = response.get("scope", "")
    scopes = tuple(str(scopes_raw).split()) if scopes_raw else GOOGLE_OAUTH_SCOPES
    return GoogleOAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_unix=now_unix + float(expires_in),
        token_type=str(response.get("token_type", "Bearer")),
        scopes=scopes,
    )


async def _default_token_exchange(endpoint: str, form: dict[str, str]) -> dict[str, object]:
    """POST the token exchange with httpx (lazy import — runtime dep)."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - environment-dependent
        from engine.google.google_auth_errors import GoogleDependencyMissingError

        raise GoogleDependencyMissingError("httpx") from None
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, data=form)
        if response.status_code != 200:
            # No response body in the error: it can echo the client secret.
            raise GoogleOAuthFlowError(
                f"token exchange failed with HTTP {response.status_code}"
            )
        decoded = response.json()
        if not isinstance(decoded, dict):
            raise GoogleOAuthFlowError("token exchange returned a non-object body")
        return dict(decoded)


class _OneShotRedirectServer:
    """Loopback listener that resolves on the first HTTP request line."""

    def __init__(self) -> None:
        self.target_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            parts = request_line.decode("latin-1").split(" ")
            target = parts[1] if len(parts) >= 2 else "/"
            body = b"<html><body>You can close this tab and return to Omni.</body></html>"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
            await writer.drain()
            if not self.target_future.done():
                self.target_future.set_result(target)
        finally:
            writer.close()


async def run_google_oauth_desktop_flow(
    token_store: GoogleTokenStore,
    *,
    open_browser: Callable[[str], object] = webbrowser.open,
    token_exchange: TokenExchangeTransport = _default_token_exchange,
    timeout_seconds: float = 300.0,
) -> GoogleOAuthTokens:
    """Run the whole loopback consent flow and persist the tokens.

    Fail closed at every step: missing client credentials, a state
    mismatch, denial, timeout, or a malformed exchange all raise
    :class:`GoogleOAuthFlowError` (or ``GoogleNotConnectedError`` upstream)
    and leave the store untouched.
    """
    credentials = token_store.load_client_credentials()
    if credentials is None:
        raise GoogleOAuthFlowError(
            "no Google OAuth client credentials — paste the client id/secret "
            "in Settings first"
        )
    state = secrets.token_urlsafe(32)
    verifier, challenge = build_pkce_pair()
    handler = _OneShotRedirectServer()
    # Loopback ONLY (local-only invariant): the listener is unreachable
    # off-box; the OS assigns an ephemeral port we then pin in redirect_uri.
    server = await asyncio.start_server(handler.handle, host="127.0.0.1", port=0)
    try:
        port = server.sockets[0].getsockname()[1]
        redirect_uri = f"http://127.0.0.1:{port}/oauth2/callback"
        open_browser(
            build_authorization_url(
                credentials, redirect_uri=redirect_uri, state=state, code_challenge=challenge
            )
        )
        try:
            target = await asyncio.wait_for(handler.target_future, timeout=timeout_seconds)
        except TimeoutError:
            raise GoogleOAuthFlowError(
                "timed out waiting for the Google consent redirect"
            ) from None
        code = parse_redirect_request_target(target, expected_state=state)
    finally:
        server.close()
        await server.wait_closed()
    response = await token_exchange(
        GOOGLE_TOKEN_ENDPOINT,
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    tokens = tokens_from_token_response(response, now_unix=time.time())
    token_store.save_tokens(tokens)
    return tokens
