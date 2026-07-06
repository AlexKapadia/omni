"""Redaction tests: a key value must never appear in ANY observable string.

Security invariant under test (claude.md §5.6): no key material in logs,
reprs, exception messages, or error chains. These tests plant a fake key
and hunt for it in every channel a leak could use — repr/str/f-strings,
translated SDK errors, logging records (including formatted output), the
RouterUnavailable aggregate, and dataclass reprs that embed messages.
Platform-independent (no DPAPI needed): runs everywhere.
"""

import logging

import pytest

from engine.router.provider_error_translation import translate_sdk_exception
from engine.router.router_errors import (
    ProviderCallError,
    ProviderErrorClass,
    ProviderFailure,
    RouterUnavailableError,
)
from engine.security.secret_redaction import (
    REDACTION_PLACEHOLDER,
    SecretApiKey,
    redact_secret_material,
)

FAKE_KEY_VALUE = "gsk_fake_9a8b7c6d5e4f3a2b1c0d_synthetic"
FAKE_KEY = SecretApiKey(FAKE_KEY_VALUE)


# ---------------------------------------------------------------------------
# SecretApiKey: the wrapper itself never discloses
# ---------------------------------------------------------------------------


def test_repr_str_and_fstrings_are_redacted() -> None:
    assert FAKE_KEY_VALUE not in repr(FAKE_KEY)
    assert FAKE_KEY_VALUE not in str(FAKE_KEY)
    assert FAKE_KEY_VALUE not in f"key is {FAKE_KEY}"
    assert FAKE_KEY_VALUE not in f"key is {FAKE_KEY!r}"
    assert REDACTION_PLACEHOLDER in str(FAKE_KEY)


def test_reveal_is_the_only_disclosure_path() -> None:
    assert FAKE_KEY.reveal() == FAKE_KEY_VALUE


def test_secret_inside_a_container_repr_is_redacted() -> None:
    """Debug-print of a dict/list holding the secret uses repr — covered."""
    assert FAKE_KEY_VALUE not in repr({"api_key": FAKE_KEY})
    assert FAKE_KEY_VALUE not in repr([FAKE_KEY])


def test_empty_key_is_refused_fail_closed() -> None:
    with pytest.raises(ValueError):
        SecretApiKey("")


def test_equality_without_disclosure() -> None:
    assert SecretApiKey(FAKE_KEY_VALUE) == FAKE_KEY
    assert SecretApiKey("other-key-value") != FAKE_KEY


# ---------------------------------------------------------------------------
# redact_secret_material: the scrubber
# ---------------------------------------------------------------------------


def test_scrubs_every_occurrence_not_just_the_first() -> None:
    text = f"a={FAKE_KEY_VALUE} b={FAKE_KEY_VALUE} c={FAKE_KEY_VALUE}"
    scrubbed = redact_secret_material(text, (FAKE_KEY,))
    assert FAKE_KEY_VALUE not in scrubbed
    assert scrubbed.count(REDACTION_PLACEHOLDER) == 3


def test_scrubs_multiple_distinct_secrets() -> None:
    other = SecretApiKey("sk-ant-different-fake-key-000111")
    text = f"groq={FAKE_KEY_VALUE} anthropic={other.reveal()}"
    scrubbed = redact_secret_material(text, (FAKE_KEY, other))
    assert FAKE_KEY_VALUE not in scrubbed
    assert other.reveal() not in scrubbed


def test_scrub_of_secret_free_text_is_identity() -> None:
    assert redact_secret_material("nothing secret here", (FAKE_KEY,)) == (
        "nothing secret here"
    )


def test_key_embedded_mid_token_is_still_scrubbed() -> None:
    """Adversarial: key glued into a URL/header without delimiters."""
    text = f"Authorization:Bearer{FAKE_KEY_VALUE}&next=1"
    assert FAKE_KEY_VALUE not in redact_secret_material(text, (FAKE_KEY,))


# ---------------------------------------------------------------------------
# The error chain: translated SDK errors and the aggregate failure
# ---------------------------------------------------------------------------


def _leaky_translated_error() -> ProviderCallError:
    class LeakySdkError(Exception):
        def __init__(self) -> None:
            super().__init__(
                f"401 for key={FAKE_KEY_VALUE}; header Bearer {FAKE_KEY_VALUE}"
            )
            self.status_code = 401

    return translate_sdk_exception(
        LeakySdkError(), provider="groq", model="llama-3.3-70b-versatile", api_key=FAKE_KEY
    )


def test_translated_error_message_str_and_repr_are_clean() -> None:
    error = _leaky_translated_error()
    assert FAKE_KEY_VALUE not in error.message
    assert FAKE_KEY_VALUE not in str(error)
    assert FAKE_KEY_VALUE not in repr(error)  # dataclass repr embeds message


def test_router_unavailable_aggregate_is_clean() -> None:
    """The plain-voice, UI-facing aggregate must also be key-free."""
    error = _leaky_translated_error()
    unavailable = RouterUnavailableError(
        "ask_synthesis",
        (
            ProviderFailure(
                provider=error.provider,
                model=error.model,
                error_class=error.error_class,
                message=error.message,
            ),
        ),
    )
    assert FAKE_KEY_VALUE not in str(unavailable)
    assert FAKE_KEY_VALUE not in repr(unavailable.failures)


def test_logged_error_records_never_carry_the_key(caplog: pytest.LogCaptureFixture) -> None:
    """End-to-end log channel: log the error every common way and inspect
    both the raw records and the formatted output."""
    error = _leaky_translated_error()
    logger = logging.getLogger("omni.test.redaction")
    with caplog.at_level(logging.DEBUG, logger="omni.test.redaction"):
        logger.error("provider call failed: %s", error)
        logger.error("details: %r", error)
        try:
            raise error
        except ProviderCallError:
            logger.exception("call blew up")
    for record in caplog.records:
        assert FAKE_KEY_VALUE not in record.getMessage()
    assert FAKE_KEY_VALUE not in caplog.text


def test_error_class_taxonomy_survives_redaction() -> None:
    """Redaction must not destroy routing information: the class and status
    still drive the fallback decision after scrubbing."""
    error = _leaky_translated_error()
    assert error.error_class is ProviderErrorClass.AUTH
    assert error.status_code == 401
    assert error.retryable is False
