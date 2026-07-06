"""Error-taxonomy tests: status mapping, retryability, SDK-missing fail-close.

The fallback policy is only as good as the classification feeding it; these
tests pin the status->class map boundary-exact (428/429/430), prove the
retryable set is exactly {ratelimit, timeout, server}, and prove a missing
provider SDK fails closed with an error NAMING the missing package.
"""

import importlib
from collections.abc import Callable

import pytest

from engine.router.provider_client_anthropic import _load_anthropic_sdk
from engine.router.provider_client_gemini import _load_genai_sdk
from engine.router.provider_client_groq import _load_groq_sdk
from engine.router.provider_error_translation import translate_sdk_exception
from engine.router.router_errors import (
    ProviderCallError,
    ProviderErrorClass,
    ProviderSdkMissingError,
    classify_provider_status,
)
from engine.security.secret_redaction import SecretApiKey

FAKE_KEY = SecretApiKey("sk-fake-key-for-tests-0123456789")


# ---------------------------------------------------------------------------
# classify_provider_status: boundary-exact status mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ProviderErrorClass.AUTH),
        (403, ProviderErrorClass.AUTH),
        (429, ProviderErrorClass.RATELIMIT),
        # Boundary neighbours of 429 must NOT classify as ratelimit.
        (428, ProviderErrorClass.SERVER),
        (430, ProviderErrorClass.SERVER),
        (500, ProviderErrorClass.SERVER),
        (502, ProviderErrorClass.SERVER),
        (503, ProviderErrorClass.SERVER),
        # Unmappable statuses default to SERVER (retry once + cascade —
        # the safe default; never a crash, never a silent auth retry-storm).
        (400, ProviderErrorClass.SERVER),
        (404, ProviderErrorClass.SERVER),
        (418, ProviderErrorClass.SERVER),
        (None, ProviderErrorClass.SERVER),
    ],
)
def test_status_code_classification(
    status: int | None, expected: ProviderErrorClass
) -> None:
    assert classify_provider_status(status) is expected


def test_timeout_signal_beats_any_status_code() -> None:
    assert classify_provider_status(500, timed_out=True) is ProviderErrorClass.TIMEOUT
    assert classify_provider_status(None, timed_out=True) is ProviderErrorClass.TIMEOUT


def test_retryable_set_is_exactly_ratelimit_timeout_server() -> None:
    def err(error_class: ProviderErrorClass) -> ProviderCallError:
        return ProviderCallError(
            provider="groq", model="m", error_class=error_class, message="x"
        )

    assert err(ProviderErrorClass.AUTH).retryable is False  # never retry a bad key
    assert err(ProviderErrorClass.RATELIMIT).retryable is True
    assert err(ProviderErrorClass.TIMEOUT).retryable is True
    assert err(ProviderErrorClass.SERVER).retryable is True


# ---------------------------------------------------------------------------
# translate_sdk_exception: SDK-agnostic translation (no SDK imports needed)
# ---------------------------------------------------------------------------


class _FakeSdkStatusError(Exception):
    """Shape-compatible with groq/anthropic SDK errors (status_code attr)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _FakeGenaiApiError(Exception):
    """Shape-compatible with google-genai APIError (code attr)."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class _FakeReadTimeout(Exception):
    """Timeout detected from the exception TYPE NAME (httpx.ReadTimeout)."""


def test_translation_maps_status_code_attribute() -> None:
    error = translate_sdk_exception(
        _FakeSdkStatusError("rate limited", 429),
        provider="groq",
        model="llama-3.3-70b-versatile",
        api_key=FAKE_KEY,
    )
    assert error.error_class is ProviderErrorClass.RATELIMIT
    assert error.status_code == 429
    assert error.provider == "groq"


def test_translation_maps_genai_code_attribute() -> None:
    error = translate_sdk_exception(
        _FakeGenaiApiError("forbidden", 403),
        provider="gemini",
        model="gemini-2.5-flash",
        api_key=FAKE_KEY,
    )
    assert error.error_class is ProviderErrorClass.AUTH
    assert error.retryable is False


def test_translation_detects_timeouts_by_type() -> None:
    for exc in (TimeoutError("slow"), _FakeReadTimeout("read timed out")):
        error = translate_sdk_exception(
            exc, provider="groq", model="m", api_key=FAKE_KEY
        )
        assert error.error_class is ProviderErrorClass.TIMEOUT


def test_translation_redacts_key_material_from_sdk_text() -> None:
    """Adversarial: the SDK echoes the Authorization header. The key must
    NOT survive translation into the typed error's message or str()."""
    leaky = _FakeSdkStatusError(
        f"401 unauthorized for Bearer {FAKE_KEY.reveal()} at api.example", 401
    )
    error = translate_sdk_exception(leaky, provider="groq", model="m", api_key=FAKE_KEY)
    assert FAKE_KEY.reveal() not in error.message
    assert FAKE_KEY.reveal() not in str(error)
    assert "[REDACTED]" in error.message


def test_translation_of_messageless_exception_still_says_something() -> None:
    error = translate_sdk_exception(
        _FakeReadTimeout(), provider="gemini", model="m", api_key=FAKE_KEY
    )
    assert error.message  # type name fallback — never an empty story


# ---------------------------------------------------------------------------
# Missing SDKs fail closed, naming the exact package to install
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("loader", "provider_name", "package_name"),
    [
        (_load_groq_sdk, "groq", "groq"),
        (_load_genai_sdk, "gemini", "google-genai"),
        (_load_anthropic_sdk, "anthropic", "anthropic"),
    ],
)
def test_missing_sdk_fails_closed_naming_the_package(
    monkeypatch: pytest.MonkeyPatch,
    loader: Callable[[], object],
    provider_name: str,
    package_name: str,
) -> None:
    def refuse_import(name: str, package: str | None = None) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", refuse_import)
    with pytest.raises(ProviderSdkMissingError) as excinfo:
        loader()
    assert excinfo.value.provider == provider_name
    assert excinfo.value.package_name == package_name
    assert package_name in str(excinfo.value)  # the message names the fix
