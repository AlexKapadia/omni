"""Microsoft OAuth 2.0 desktop (loopback) flow with PKCE — Calendar.Read only."""

from __future__ import annotations

import asyncio
import secrets
import time
import webbrowser
from collections.abc import Awaitable, Callable
from urllib.parse import quote

from engine.google.oauth_desktop_flow import (
    _default_token_exchange,
    _OneShotRedirectServer,
    build_pkce_pair,
    parse_redirect_request_target,
)
from engine.microsoft.dpapi_microsoft_token_store import (
    MicrosoftOAuthClientCredentials,
    MicrosoftOAuthTokens,
    MicrosoftTokenStore,
)
from engine.microsoft.microsoft_auth_errors import MicrosoftOAuthFlowError

MICROSOFT_AUTHORIZATION_ENDPOINT = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
)
MICROSOFT_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"  # noqa: S105

MICROSOFT_OAUTH_SCOPES: tuple[str, str] = (
    "Calendars.Read",
    "offline_access",
)

TokenExchangeTransport = Callable[[str, dict[str, str]], Awaitable[dict[str, object]]]


def build_authorization_url(
    credentials: MicrosoftOAuthClientCredentials,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    scope = quote(" ".join(MICROSOFT_OAUTH_SCOPES), safe="")
    return (
        f"{MICROSOFT_AUTHORIZATION_ENDPOINT}"
        f"?client_id={quote(credentials.client_id, safe='')}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        "&response_type=code"
        f"&scope={scope}"
        f"&state={quote(state, safe='')}"
        f"&code_challenge={quote(code_challenge, safe='')}"
        "&code_challenge_method=S256"
        "&prompt=consent"
    )


def tokens_from_token_response(
    response: dict[str, object], *, now_unix: float, existing_refresh_token: str | None = None
) -> MicrosoftOAuthTokens:
    access_token = response.get("access_token")
    expires_in = response.get("expires_in")
    refresh_token = response.get("refresh_token", existing_refresh_token)
    if not isinstance(access_token, str) or not access_token:
        raise MicrosoftOAuthFlowError("token response carried no access token")
    if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0:
        raise MicrosoftOAuthFlowError("token response carried no usable expiry")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise MicrosoftOAuthFlowError("token response carried no refresh token")
    scopes_raw = response.get("scope", "")
    scopes = tuple(str(scopes_raw).split()) if scopes_raw else MICROSOFT_OAUTH_SCOPES
    return MicrosoftOAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_unix=now_unix + float(expires_in),
        token_type=str(response.get("token_type", "Bearer")),
        scopes=scopes,
    )


async def run_microsoft_oauth_desktop_flow(
    token_store: MicrosoftTokenStore,
    *,
    open_browser: Callable[[str], object] = webbrowser.open,
    token_exchange: TokenExchangeTransport = _default_token_exchange,
    timeout_seconds: float = 300.0,
) -> MicrosoftOAuthTokens:
    credentials = token_store.load_client_credentials()
    if credentials is None:
        raise MicrosoftOAuthFlowError(
            "no Microsoft OAuth client credentials — paste the client id/secret in Settings first"
        )
    state = secrets.token_urlsafe(32)
    verifier, challenge = build_pkce_pair()
    handler = _OneShotRedirectServer()
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
            raise MicrosoftOAuthFlowError(
                "timed out waiting for the Microsoft consent redirect"
            ) from None
        from engine.google.google_auth_errors import GoogleOAuthFlowError

        try:
            code = parse_redirect_request_target(target, expected_state=state)
        except GoogleOAuthFlowError as exc:
            raise MicrosoftOAuthFlowError(str(exc)) from exc
    finally:
        server.close()
        await server.wait_closed()
    response = await token_exchange(
        MICROSOFT_TOKEN_ENDPOINT,
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    existing = token_store.load_tokens()
    tokens = tokens_from_token_response(
        response,
        now_unix=time.time(),
        existing_refresh_token=existing.refresh_token if existing else None,
    )
    token_store.save_tokens(tokens)
    return tokens
