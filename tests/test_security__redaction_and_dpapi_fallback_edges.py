"""Redaction + DPAPI edge branches: short-secret exact match, equality with
foreign types, hashing, and the platform guards / non-Windows fallback.

These target the branches the main redaction suite leaves uncovered:
- ``SecretApiKey.__eq__`` against a non-secret returns ``NotImplemented`` so
  Python falls back to identity (never accidental equality, never a crash).
- ``__hash__`` makes equal keys collapse in a set (custody containers work).
- The short-secret path (< 6 chars) redacts ONLY on an exact whole-string
  match — a fragment must never trigger runaway substring replacement.
- ``dpapi_protect``/``dpapi_unprotect`` fail closed off Windows, and the
  non-Windows ``_run_dpapi_call`` stub raises rather than returning plaintext.

The raw ctypes CryptProtectData/CryptUnprotectData syscalls are the one
un-fakeable Windows-DPAPI boundary and are exercised by the round-trip
suite; here we prove every non-syscall branch around them.
"""

import importlib
import sys

import pytest

import engine.security.dpapi_windows_crypto as dpapi_module
from engine.security.dpapi_windows_crypto import (
    DpapiUnavailableError,
    dpapi_protect,
    dpapi_unprotect,
)
from engine.security.secret_redaction import (
    REDACTION_PLACEHOLDER,
    SecretApiKey,
    redact_secret_material,
)

# 6 == _MIN_SUBSTRING_REDACTION_LENGTH: at/above this length a value is
# scrubbed as a substring; below it, only an exact whole-string match is.
_SIX_CHAR_VALUE = "abcdef"
_FIVE_CHAR_VALUE = "abcde"


# ---------------------------------------------------------------------------
# SecretApiKey equality / hashing edge branches
# ---------------------------------------------------------------------------


def test_eq_with_foreign_type_is_not_equal_and_never_crashes() -> None:
    """__eq__ returns NotImplemented for non-secrets -> identity fallback."""
    key = SecretApiKey("gsk_fake_synthetic_key_000")
    # Python consumes NotImplemented and falls back to "not equal".
    assert (key == 42) is False
    assert (key == "gsk_fake_synthetic_key_000") is False  # a bare str is NOT a key
    assert (key == object()) is False
    assert key != 42  # the reflected/!= path also holds


def test_equal_secrets_collapse_in_a_set_via_hash() -> None:
    """Two keys with the same value hash equal, so a set dedups them; a
    different value stays distinct. Proves __hash__ tracks value, not id."""
    same_a = SecretApiKey("sk-ant-identical-value-123456")
    same_b = SecretApiKey("sk-ant-identical-value-123456")
    different = SecretApiKey("sk-ant-other-value-99999999")
    assert hash(same_a) == hash(same_b)
    collected = {same_a, same_b, different}
    assert len(collected) == 2  # the duplicate collapsed; the distinct survived
    # Usable as a dict key without disclosing the value in the repr.
    lookup = {same_a: "wired"}
    assert lookup[same_b] == "wired"  # equal key retrieves the same slot


# ---------------------------------------------------------------------------
# redact_secret_material: the short-secret exact-match branch
# ---------------------------------------------------------------------------


def test_short_secret_redacts_only_on_exact_whole_string_match() -> None:
    """A sub-6-char secret is redacted when the WHOLE string equals it..."""
    short = SecretApiKey(_FIVE_CHAR_VALUE)
    assert redact_secret_material(_FIVE_CHAR_VALUE, (short,)) == REDACTION_PLACEHOLDER


def test_short_secret_is_never_over_redacted_as_a_substring() -> None:
    """...but the same short secret embedded in a larger string is LEFT ALONE:
    exact-match only, so no runaway replacement of a common fragment."""
    short = SecretApiKey(_FIVE_CHAR_VALUE)
    surrounding = f"x{_FIVE_CHAR_VALUE}x and {_FIVE_CHAR_VALUE} again"
    # Not a whole-string match -> returned byte-for-byte unchanged.
    assert redact_secret_material(surrounding, (short,)) == surrounding


def test_length_boundary_six_redacts_as_substring_five_does_not() -> None:
    """Boundary at _MIN_SUBSTRING_REDACTION_LENGTH (6): a 6-char secret IS
    scrubbed mid-string; a 5-char one is not (on/just-under the cutoff)."""
    six = SecretApiKey(_SIX_CHAR_VALUE)
    five = SecretApiKey(_FIVE_CHAR_VALUE)
    text_six = f"prefix-{_SIX_CHAR_VALUE}-suffix"
    text_five = f"prefix-{_FIVE_CHAR_VALUE}-suffix"
    assert _SIX_CHAR_VALUE not in redact_secret_material(text_six, (six,))
    assert REDACTION_PLACEHOLDER in redact_secret_material(text_six, (six,))
    # 5-char is below the substring floor: embedded, so untouched.
    assert redact_secret_material(text_five, (five,)) == text_five


def test_short_and_long_secrets_mixed_scrub_correctly() -> None:
    """A whole-string short secret redacts to the placeholder; a long secret
    inside the same run of calls still scrubs as a substring."""
    short = SecretApiKey("k1")  # 2 chars, exact-only
    long_secret = SecretApiKey("gsk_long_enough_to_substring_scrub")
    assert redact_secret_material("k1", (short, long_secret)) == REDACTION_PLACEHOLDER
    leaked = f"header={long_secret.reveal()};tail"
    scrubbed = redact_secret_material(leaked, (short, long_secret))
    assert long_secret.reveal() not in scrubbed
    assert scrubbed == f"header={REDACTION_PLACEHOLDER};tail"


# ---------------------------------------------------------------------------
# DPAPI platform guards + non-Windows fallback (fail closed, never plaintext)
# ---------------------------------------------------------------------------


def test_dpapi_protect_refuses_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The platform guard fires before any syscall: no encryption off Windows,
    and crucially no silent plaintext passthrough."""
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(DpapiUnavailableError):
        dpapi_protect(b"secret-plaintext")


def test_dpapi_unprotect_refuses_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(DpapiUnavailableError):
        dpapi_unprotect(b"\x01\x02ciphertext")


def test_non_windows_module_defines_a_failing_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reloading the module under a non-Windows platform selects the stub
    ``_run_dpapi_call`` branch, which fails closed (never returns bytes).
    Restores the real Windows module afterward so nothing downstream breaks."""
    monkeypatch.setattr(sys, "platform", "linux")
    reloaded = importlib.reload(dpapi_module)
    try:
        with pytest.raises(reloaded.DpapiUnavailableError):
            reloaded._run_dpapi_call("CryptProtectData", b"anything")
    finally:
        # Restore win32 platform and rebuild the real (syscall) module.
        monkeypatch.undo()
        importlib.reload(dpapi_module)
