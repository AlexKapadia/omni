"""Translates raw SDK exceptions into the router's typed error taxonomy.

Purpose: one SDK-agnostic mechanism shared by all three provider clients —
extract an HTTP status if the exception carries one, detect timeouts, map
onto :class:`ProviderErrorClass`, and REDACT key material from the message
before it can propagate into logs, ledgers, or the UI.
Pipeline position: called inside each provider client's ``except`` block;
deliberately free of any SDK import so it is fully unit-testable without
the SDKs installed.

Security invariant: the returned error's message has passed through
``redact_secret_material`` — an SDK echoing an API key (e.g. in a request
dump) can never leak it beyond this boundary.
"""

import asyncio

from engine.router.router_errors import ProviderCallError, classify_provider_status
from engine.security.secret_redaction import SecretApiKey, redact_secret_material

# Exception-type-name fragments that signal a timeout when no status code
# exists (covers httpx.TimeoutException, APITimeoutError, DeadlineExceeded
# and friends across all three SDKs without importing any of them).
_TIMEOUT_NAME_FRAGMENTS = ("timeout", "deadline")


def _extract_status_code(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an SDK exception, without SDK imports.

    All three SDKs expose ``status_code`` (groq/anthropic, httpx-based) or
    ``code`` (google-genai APIError) as an int attribute.
    """
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    return None


def _looks_like_timeout(exc: BaseException) -> bool:
    """Timeout detection: real timeout types plus SDK timeout-named types."""
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return True
    type_name = type(exc).__name__.lower()
    return any(fragment in type_name for fragment in _TIMEOUT_NAME_FRAGMENTS)


def translate_sdk_exception(
    exc: BaseException,
    *,
    provider: str,
    model: str,
    api_key: SecretApiKey,
) -> ProviderCallError:
    """Build the typed, REDACTED ProviderCallError for one SDK failure."""
    status_code = _extract_status_code(exc)
    error_class = classify_provider_status(status_code, timed_out=_looks_like_timeout(exc))
    # Redaction invariant: SDK text is untrusted w.r.t. secrets — scrub the
    # key before the message leaves the client boundary.
    message = redact_secret_material(str(exc) or type(exc).__name__, (api_key,))
    return ProviderCallError(
        provider=provider,
        model=model,
        error_class=error_class,
        message=message,
        status_code=status_code,
    )
