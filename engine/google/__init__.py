"""Google integration layer: OAuth desktop flow, DPAPI token custody, and
typed REST wrappers for Calendar / People / Gmail-drafts.

Where it sits: below ``engine.agents`` (the tools are the only callers) and
above ``engine.security`` (DPAPI, kill switch). The router is NOT involved —
Google API calls are user-approved actions, not model calls, but they honour
the same global kill switch (fail closed on egress).

Binding invariants carried by this package:
- Scopes pinned to exactly calendar.events + contacts + gmail.compose.
- DRAFT-ONLY: no code path can dispatch mail; drafts are the entire Gmail
  capability.
- Tokens and client secrets live DPAPI-encrypted only; never in logs.
"""

from engine.google.dpapi_google_token_store import (
    GoogleOAuthClientCredentials,
    GoogleOAuthTokens,
    GoogleTokenStore,
)
from engine.google.google_auth_errors import (
    GoogleApiCallError,
    GoogleDependencyMissingError,
    GoogleEgressBlockedError,
    GoogleError,
    GoogleNotConnectedError,
    GoogleOAuthFlowError,
    GoogleTokenRefreshError,
)
from engine.google.google_session import DpapiGoogleSession, GoogleSession
from engine.google.oauth_desktop_flow import (
    GOOGLE_OAUTH_SCOPES,
    run_google_oauth_desktop_flow,
)

__all__ = [
    "GOOGLE_OAUTH_SCOPES",
    "DpapiGoogleSession",
    "GoogleApiCallError",
    "GoogleDependencyMissingError",
    "GoogleEgressBlockedError",
    "GoogleError",
    "GoogleNotConnectedError",
    "GoogleOAuthClientCredentials",
    "GoogleOAuthFlowError",
    "GoogleOAuthTokens",
    "GoogleSession",
    "GoogleTokenRefreshError",
    "GoogleTokenStore",
    "run_google_oauth_desktop_flow",
]
