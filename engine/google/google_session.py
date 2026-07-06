"""Authorised Google HTTP session: token custody, refresh, and transport.

Purpose: the ONE object that can put an Authorization header on a Google
request. The gateway builds typed requests and hands them here; this module
loads DPAPI tokens, refreshes them when they are inside the clock-skew
window, and performs the HTTP call (httpx, lazily imported). Tests inject a
:class:`GoogleSession` fake — no network, no tokens, no httpx needed.
Pipeline position: below ``google_api_gateway``, above the DPAPI token
store; constructed by the (deferred) server wiring.

Security invariants:
- FAIL CLOSED on "not connected": no stored tokens -> typed
  ``GoogleNotConnectedError`` before any bytes leave the machine.
- Refresh is clock-skew tolerant (see the store's boundary) and a failed
  refresh raises a typed error — never a silent expired-token call.
- Tokens never appear in error messages; response bodies of failed calls
  are summarised, not echoed.
"""

import time
from collections.abc import Awaitable, Callable

from engine.google.dpapi_google_token_store import GoogleOAuthTokens, GoogleTokenStore
from engine.google.google_auth_errors import (
    GoogleApiCallError,
    GoogleDependencyMissingError,
    GoogleNotConnectedError,
    GoogleTokenRefreshError,
)
from engine.google.oauth_desktop_flow import GOOGLE_TOKEN_ENDPOINT, tokens_from_token_response

# Injectable transports so every path is testable offline.
FormPoster = Callable[[str, dict[str, str]], Awaitable[dict[str, object]]]


class GoogleSession:
    """Interface the gateway codes against (plain base class so fakes are
    trivial and isinstance checks work).

    ``request_json`` performs one authorised HTTPS call and returns the
    decoded JSON object; implementations raise the typed errors above.
    """

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        raise NotImplementedError


class DpapiGoogleSession(GoogleSession):
    """The real session: DPAPI tokens + refresh + httpx transport."""

    def __init__(
        self,
        token_store: GoogleTokenStore | None = None,
        *,
        token_refresh_post: FormPoster | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token_store = token_store if token_store is not None else GoogleTokenStore()
        self._token_refresh_post = token_refresh_post
        self._clock = clock

    async def _fresh_access_token(self) -> str:
        """A usable access token, refreshing inside the skew window."""
        tokens = self._token_store.load_tokens()
        if tokens is None:
            # fail-closed: not connected means NO call, not an anonymous one.
            raise GoogleNotConnectedError
        if tokens.expiring_soon(self._clock()):
            tokens = await self._refresh(tokens)
        return tokens.access_token

    async def _refresh(self, tokens: GoogleOAuthTokens) -> GoogleOAuthTokens:
        """Exchange the refresh token; persist and return the new set."""
        credentials = self._token_store.load_client_credentials()
        if credentials is None:
            raise GoogleTokenRefreshError(
                "cannot refresh: Google OAuth client credentials are missing"
            )
        post = self._token_refresh_post or _default_form_post
        try:
            response = await post(
                GOOGLE_TOKEN_ENDPOINT,
                {
                    "client_id": credentials.client_id,
                    "client_secret": credentials.client_secret,
                    "refresh_token": tokens.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except GoogleDependencyMissingError:
            raise
        except Exception as error:  # transport failure -> typed, redacted
            raise GoogleTokenRefreshError(
                f"token refresh transport failed: {type(error).__name__}"
            ) from None
        try:
            refreshed = tokens_from_token_response(
                response, now_unix=self._clock(), existing_refresh_token=tokens.refresh_token
            )
        except Exception as error:
            raise GoogleTokenRefreshError(f"token refresh response invalid: {error}") from None
        self._token_store.save_tokens(refreshed)
        return refreshed

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """One authorised call. Non-2xx or non-object bodies fail typed."""
        access_token = await self._fresh_access_token()
        try:
            import httpx
        except ImportError:  # pragma: no cover - environment-dependent
            raise GoogleDependencyMissingError("httpx") from None
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    # The ONLY place the access token is used; never logged.
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as error:
                raise GoogleApiCallError(url, None, type(error).__name__) from None
        if not (200 <= response.status_code < 300):
            # Summarise, never echo: bodies can be huge and may reflect
            # request content — the status is what the user needs.
            raise GoogleApiCallError(url, response.status_code, "request rejected")
        try:
            decoded = response.json()
        except ValueError:
            raise GoogleApiCallError(url, response.status_code, "non-JSON response") from None
        if not isinstance(decoded, dict):
            raise GoogleApiCallError(url, response.status_code, "non-object response")
        return dict(decoded)


async def _default_form_post(endpoint: str, form: dict[str, str]) -> dict[str, object]:
    """POST a form with httpx (lazy import); used for token refresh."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - environment-dependent
        raise GoogleDependencyMissingError("httpx") from None
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, data=form)
        if response.status_code != 200:
            raise GoogleTokenRefreshError(
                f"token refresh failed with HTTP {response.status_code}"
            )
        decoded = response.json()
        if not isinstance(decoded, dict):
            raise GoogleTokenRefreshError("token refresh returned a non-object body")
        return dict(decoded)
