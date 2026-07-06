"""Typed errors for the Google OAuth/session/gateway layer.

Purpose: every Google-facing failure is a NAMED error with a plain-voice
message the UI can show verbatim. The gateway and session fail CLOSED with
these — there is no "try anyway" path when the account is not connected,
the kill switch is engaged, or a dependency is missing.

Security invariant: messages never contain tokens, client secrets, or raw
response bodies — only statuses and human-readable reasons.
"""


class GoogleError(Exception):
    """Base class for every typed Google-layer failure."""


class GoogleNotConnectedError(GoogleError):
    """No stored Google tokens — the user has not connected an account.

    Fail closed: Google-facing tools refuse with this instead of attempting
    an unauthenticated call.
    """

    def __init__(self) -> None:
        super().__init__(
            "Google account not connected — connect it in Settings before "
            "approving Google actions."
        )


class GoogleEgressBlockedError(GoogleError):
    """The global kill switch is engaged; no Google call may leave the box.

    Mirrors the router's egress refusal (claude.md §5.6): fail closed on
    egress, never on the user's own local data.
    """

    def __init__(self) -> None:
        super().__init__(
            "The kill switch is engaged — all external calls are halted. "
            "Google actions are refused until it is turned off."
        )


class GoogleOAuthFlowError(GoogleError):
    """The desktop OAuth flow failed (denied consent, bad state, timeout)."""


class GoogleTokenRefreshError(GoogleError):
    """The refresh-token exchange failed; the user must reconnect."""


class GoogleApiCallError(GoogleError):
    """A Google API call returned an error or an unparseable response."""

    def __init__(self, api_name: str, status_code: int | None, reason: str) -> None:
        self.api_name = api_name
        self.status_code = status_code
        status = "no response" if status_code is None else f"HTTP {status_code}"
        super().__init__(f"Google {api_name} call failed ({status}): {reason}")


class GoogleDependencyMissingError(GoogleError):
    """The lazily-imported HTTP client is not installed in this environment."""

    def __init__(self, package_name: str) -> None:
        self.package_name = package_name
        super().__init__(
            f"the '{package_name}' package is required for Google calls and is "
            "not installed — see docs/progress/pending-deps.txt"
        )
