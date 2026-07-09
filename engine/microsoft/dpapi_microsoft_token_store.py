"""DPAPI-encrypted custody of Microsoft OAuth tokens + client credentials."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from engine.security.dpapi_windows_crypto import dpapi_protect, dpapi_unprotect

CLOCK_SKEW_TOLERANCE_SECONDS = 300.0
_CLIENT_ID_ENV_VAR = "MICROSOFT_OAUTH_CLIENT_ID"
_CLIENT_SECRET_ENV_VAR = "MICROSOFT_OAUTH_CLIENT_SECRET"  # noqa: S105


def default_microsoft_token_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "Omni" / "microsoft_tokens.bin"


@dataclass(frozen=True)
class MicrosoftOAuthTokens:
    access_token: str
    refresh_token: str
    expires_at_unix: float
    token_type: str = "Bearer"  # noqa: S105
    scopes: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return f"MicrosoftOAuthTokens(expires_at_unix={self.expires_at_unix!r}, tokens=<redacted>)"

    def expiring_soon(self, now_unix: float | None = None) -> bool:
        now = time.time() if now_unix is None else now_unix
        return now >= self.expires_at_unix - CLOCK_SKEW_TOLERANCE_SECONDS


@dataclass(frozen=True)
class MicrosoftOAuthClientCredentials:
    client_id: str
    client_secret: str

    def __repr__(self) -> str:
        return (
            f"MicrosoftOAuthClientCredentials(client_id={self.client_id!r}, "
            "client_secret=<redacted>)"
        )


class MicrosoftTokenStore:
    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = (
            store_path if store_path is not None else default_microsoft_token_store_path()
        )

    def load_tokens(self) -> MicrosoftOAuthTokens | None:
        blob = self._read_blob()
        raw = blob.get("tokens")
        if not isinstance(raw, dict):
            return None
        try:
            return MicrosoftOAuthTokens(
                access_token=str(raw["access_token"]),
                refresh_token=str(raw["refresh_token"]),
                expires_at_unix=float(raw["expires_at_unix"]),
                token_type=str(raw.get("token_type", "Bearer")),
                scopes=tuple(str(s) for s in raw.get("scopes", [])),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def save_tokens(self, tokens: MicrosoftOAuthTokens) -> None:
        blob = self._read_blob()
        blob["tokens"] = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at_unix": tokens.expires_at_unix,
            "token_type": tokens.token_type,
            "scopes": list(tokens.scopes),
        }
        self._write_blob(blob)

    def load_client_credentials(self) -> MicrosoftOAuthClientCredentials | None:
        blob = self._read_blob()
        raw = blob.get("client")
        if isinstance(raw, dict):
            try:
                return MicrosoftOAuthClientCredentials(
                    client_id=str(raw["client_id"]),
                    client_secret=str(raw["client_secret"]),
                )
            except (KeyError, TypeError, ValueError):
                pass
        client_id = os.environ.get(_CLIENT_ID_ENV_VAR, "").strip()
        client_secret = os.environ.get(_CLIENT_SECRET_ENV_VAR, "").strip()
        if client_id and client_secret:
            return MicrosoftOAuthClientCredentials(client_id, client_secret)
        return None

    def save_client_credentials(self, credentials: MicrosoftOAuthClientCredentials) -> None:
        blob = self._read_blob()
        blob["client"] = {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        }
        self._write_blob(blob)

    def _read_blob(self) -> dict[str, object]:
        if not self._store_path.exists():
            return {}
        plaintext = dpapi_unprotect(self._store_path.read_bytes())
        parsed = json.loads(plaintext.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("microsoft token store blob is not a JSON object")
        return dict(parsed)

    def _write_blob(self, blob: dict[str, object]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        ciphertext = dpapi_protect(json.dumps(blob).encode("utf-8"))
        temp_path = self._store_path.with_suffix(".bin.tmp")
        temp_path.write_bytes(ciphertext)
        temp_path.replace(self._store_path)
