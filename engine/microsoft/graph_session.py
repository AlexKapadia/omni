"""Authorised Microsoft Graph session: token refresh + HTTP transport."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from engine.microsoft.dpapi_microsoft_token_store import MicrosoftOAuthTokens, MicrosoftTokenStore
from engine.microsoft.microsoft_auth_errors import (
    MicrosoftApiCallError,
    MicrosoftDependencyMissingError,
    MicrosoftNotConnectedError,
    MicrosoftTokenRefreshError,
)
from engine.microsoft.oauth_desktop_flow import (
    MICROSOFT_TOKEN_ENDPOINT,
    tokens_from_token_response,
)

FormPoster = Callable[[str, dict[str, str]], Awaitable[dict[str, object]]]


class MicrosoftSession:
    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        raise NotImplementedError


class DpapiMicrosoftSession(MicrosoftSession):
    def __init__(
        self,
        token_store: MicrosoftTokenStore | None = None,
        *,
        token_refresh_post: FormPoster | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token_store = token_store if token_store is not None else MicrosoftTokenStore()
        self._token_refresh_post = token_refresh_post
        self._clock = clock

    async def _fresh_access_token(self) -> str:
        tokens = self._token_store.load_tokens()
        if tokens is None:
            raise MicrosoftNotConnectedError
        if tokens.expiring_soon(self._clock()):
            tokens = await self._refresh(tokens)
        return tokens.access_token

    async def _refresh(self, tokens: MicrosoftOAuthTokens) -> MicrosoftOAuthTokens:
        credentials = self._token_store.load_client_credentials()
        if credentials is None:
            raise MicrosoftTokenRefreshError("no client credentials for refresh")
        poster = self._token_refresh_post or _default_refresh_post
        response = await poster(
            MICROSOFT_TOKEN_ENDPOINT,
            {
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "refresh_token": tokens.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        refreshed = tokens_from_token_response(
            response, now_unix=self._clock(), existing_refresh_token=tokens.refresh_token
        )
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
        token = await self._fresh_access_token()
        try:
            import httpx
        except ImportError as exc:
            raise MicrosoftDependencyMissingError("httpx") from exc
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code >= 400:
            raise MicrosoftApiCallError(f"Graph API HTTP {response.status_code}")
        decoded = response.json()
        if not isinstance(decoded, dict):
            raise MicrosoftApiCallError("Graph API returned a non-object body")
        return dict(decoded)


async def _default_refresh_post(endpoint: str, form: dict[str, str]) -> dict[str, object]:
    from engine.google.oauth_desktop_flow import _default_token_exchange

    return await _default_token_exchange(endpoint, form)
