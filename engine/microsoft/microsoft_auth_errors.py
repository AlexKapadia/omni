"""Typed errors for Microsoft Graph OAuth and API calls."""


class MicrosoftError(Exception):
    """Base for Microsoft integration errors."""


class MicrosoftNotConnectedError(MicrosoftError):
    """No stored tokens — fail closed before any Graph call."""


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
