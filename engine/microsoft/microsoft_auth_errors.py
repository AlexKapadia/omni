"""Typed errors for Microsoft Graph OAuth and API calls."""


class MicrosoftError(Exception):
    """Base for Microsoft integration errors."""


class MicrosoftNotConnectedError(MicrosoftError):
    """No stored tokens — fail closed before any Graph call."""


class MicrosoftEgressBlockedError(MicrosoftError):
    """The global kill switch is engaged; no Graph call may leave the box.

    Mirrors the Google gateway's egress refusal (claude.md §5.6): fail closed
    on egress, never on the user's own local data.
    """

    def __init__(self) -> None:
        super().__init__(
            "The kill switch is engaged — all external calls are halted. "
            "Microsoft Graph actions are refused until it is turned off."
        )


class MicrosoftOAuthFlowError(MicrosoftError):
    """Consent or token exchange failed."""


class MicrosoftTokenRefreshError(MicrosoftError):
    """Refresh token exchange failed."""


class MicrosoftApiCallError(MicrosoftError):
    """Graph API returned an error status."""


class MicrosoftDependencyMissingError(MicrosoftError):
    def __init__(self, package: str) -> None:
        super().__init__(f"dependency {package!r} is not installed")
        self.package = package
