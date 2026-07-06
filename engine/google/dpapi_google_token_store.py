"""DPAPI-encrypted custody of Google OAuth tokens + client credentials.

Purpose: the ONLY place Google OAuth material is read or written. Tokens
from the desktop flow and the user-pasted OAuth client id/secret are
DPAPI-encrypted (per Windows user) into ``%LOCALAPPDATA%/Omni/
google_tokens.bin``; in development the environment variables
``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET`` act as a
client-credential fallback (populated by the dev runner — engine code never
reads ``.env`` directly).
Pipeline position: written by ``oauth_desktop_flow`` after the code
exchange; read by ``google_session`` on every authorised call.

Security invariants (claude.md §5.6 project bindings):
- Plaintext tokens never touch disk: the on-disk blob is DPAPI ciphertext.
- DPAPI failures propagate (fail closed — a corrupt or foreign-user blob is
  never silently treated as "not connected").
- No token material in logs, reprs, or error messages, ever.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from engine.security.dpapi_windows_crypto import dpapi_protect, dpapi_unprotect

# Refresh this many seconds BEFORE nominal expiry: absorbs clock skew between
# this box and Google's token service plus request transit time.
CLOCK_SKEW_TOLERANCE_SECONDS = 300.0

_CLIENT_ID_ENV_VAR = "GOOGLE_OAUTH_CLIENT_ID"
_CLIENT_SECRET_ENV_VAR = "GOOGLE_OAUTH_CLIENT_SECRET"  # noqa: S105 — env-var NAME, not a value


def default_google_token_store_path() -> Path:
    """``%LOCALAPPDATA%/Omni/google_tokens.bin`` (home fallback off-Windows)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "Omni" / "google_tokens.bin"


@dataclass(frozen=True)
class GoogleOAuthTokens:
    """One token set as stored. ``expires_at_unix`` is absolute (epoch
    seconds) so expiry survives process restarts; repr never shows values."""

    access_token: str
    refresh_token: str
    expires_at_unix: float
    token_type: str = "Bearer"  # noqa: S105 — OAuth token *type*, not a secret
    scopes: tuple[str, ...] = ()

    def __repr__(self) -> str:  # no token material in logs/tracebacks, ever
        return f"GoogleOAuthTokens(expires_at_unix={self.expires_at_unix!r}, tokens=<redacted>)"

    def expiring_soon(self, now_unix: float | None = None) -> bool:
        """Should the session refresh before using the access token?

        Boundary (exact): refresh when ``now >= expires_at - skew``.
        """
        now = time.time() if now_unix is None else now_unix
        return now >= self.expires_at_unix - CLOCK_SKEW_TOLERANCE_SECONDS


@dataclass(frozen=True)
class GoogleOAuthClientCredentials:
    """The OAuth client id/secret the user pasted (or dev env fallback)."""

    client_id: str
    client_secret: str

    def __repr__(self) -> str:  # secret never in logs/tracebacks
        return (
            f"GoogleOAuthClientCredentials(client_id={self.client_id!r}, "
            "client_secret=<redacted>)"
        )


class GoogleTokenStore:
    """Reads/writes the DPAPI-encrypted Google OAuth blob."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = (
            store_path if store_path is not None else default_google_token_store_path()
        )

    def load_tokens(self) -> GoogleOAuthTokens | None:
        """The stored token set, or None when never connected."""
        blob = self._read_blob()
        raw = blob.get("tokens")
        if not isinstance(raw, dict):
            return None
        try:
            return GoogleOAuthTokens(
                access_token=str(raw["access_token"]),
                refresh_token=str(raw["refresh_token"]),
                expires_at_unix=float(raw["expires_at_unix"]),
                token_type=str(raw.get("token_type", "Bearer")),
                scopes=tuple(str(s) for s in raw.get("scopes", [])),
            )
        except (KeyError, TypeError, ValueError):
            # fail-closed on shape: a mangled blob reads as "not connected"
            # ONLY when DPAPI itself succeeded (tamper still raises above).
            return None

    def save_tokens(self, tokens: GoogleOAuthTokens) -> None:
        """Persist a token set, preserving stored client credentials."""
        blob = self._read_blob()
        blob["tokens"] = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at_unix": tokens.expires_at_unix,
            "token_type": tokens.token_type,
            "scopes": list(tokens.scopes),
        }
        self._write_blob(blob)

    def clear_tokens(self) -> None:
        """Disconnect: drop tokens (client credentials survive)."""
        blob = self._read_blob()
        if "tokens" in blob:
            del blob["tokens"]
            self._write_blob(blob)

    def load_client_credentials(self) -> GoogleOAuthClientCredentials | None:
        """Client id/secret: DPAPI store first, then the dev env fallback."""
        blob = self._read_blob()
        raw = blob.get("client")
        if isinstance(raw, dict):
            client_id = str(raw.get("client_id", "")).strip()
            client_secret = str(raw.get("client_secret", "")).strip()
            if client_id and client_secret:
                return GoogleOAuthClientCredentials(client_id, client_secret)
        env_id = os.environ.get(_CLIENT_ID_ENV_VAR, "").strip()
        env_secret = os.environ.get(_CLIENT_SECRET_ENV_VAR, "").strip()
        if env_id and env_secret:
            return GoogleOAuthClientCredentials(env_id, env_secret)
        return None

    def save_client_credentials(self, credentials: GoogleOAuthClientCredentials) -> None:
        """Persist the user-pasted OAuth client id/secret (onboarding/Settings)."""
        blob = self._read_blob()
        blob["client"] = {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        }
        self._write_blob(blob)

    def _read_blob(self) -> dict[str, object]:
        """Decrypt and parse the blob; a missing file is an empty store."""
        if not self._store_path.exists():
            return {}
        ciphertext = self._store_path.read_bytes()
        # DPAPI decrypt: per-user; raises (fail closed) on tamper/other-user.
        plaintext = dpapi_unprotect(ciphertext)
        parsed = json.loads(plaintext.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("google token store blob is not a JSON object")
        return dict(parsed)

    def _write_blob(self, blob: dict[str, object]) -> None:
        """Serialise, DPAPI-encrypt, and write atomically (replace-on-write)."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        ciphertext = dpapi_protect(json.dumps(blob).encode("utf-8"))
        # Write-then-replace: a crash mid-write never truncates the store.
        temp_path = self._store_path.with_suffix(".bin.tmp")
        temp_path.write_bytes(ciphertext)
        temp_path.replace(self._store_path)
