"""DPAPI + key-store tests: real per-user encryption on this Windows box.

Runs the REAL CryptProtectData/CryptUnprotectData (purely local — nothing
leaves the machine), proving round-trip fidelity byte-for-byte, tamper
rejection (fail closed), that the on-disk blob is genuinely ciphertext,
and the key-store contract: store beats env, unknown providers refused,
deletes surgical. All paths are tmp_path — never the user's real keys.bin.
"""

import json
import sys
from pathlib import Path

import pytest

from engine.security.dpapi_windows_crypto import (
    DpapiOperationError,
    dpapi_protect,
    dpapi_unprotect,
)
from engine.security.provider_key_store import ProviderKeyStore
from engine.security.secret_redaction import SecretApiKey

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="DPAPI is Windows-only (dev box + release target)"
)

FAKE_GROQ_KEY = "gsk_fake_totally_synthetic_key_1234567890"


# ---------------------------------------------------------------------------
# Raw DPAPI round-trips (byte fidelity + fail-closed tamper handling)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"groq": "gsk_fake"}',
        "unicode: ключ 密钥 🔑".encode(),
        bytes(range(256)),  # every byte value survives
        b"x" * 65_536,  # a large blob
        b"",  # degenerate: empty payload
    ],
    # Short ids: the default ids embed the payload bytes, and the 64 KiB case
    # overflows Windows' 32,767-char env-var limit via PYTEST_CURRENT_TEST.
    ids=["empty-json", "small-json", "unicode", "all-byte-values", "64KiB", "empty"],
)
def test_protect_unprotect_round_trips_exactly(payload: bytes) -> None:
    ciphertext = dpapi_protect(payload)
    assert dpapi_unprotect(ciphertext) == payload  # byte-for-byte


def test_ciphertext_is_not_the_plaintext() -> None:
    payload = b"secret-key-material-here"
    ciphertext = dpapi_protect(payload)
    assert payload not in ciphertext  # actually encrypted, not encoded


def test_protect_is_nondeterministic_but_both_blobs_decrypt() -> None:
    """DPAPI salts each blob; two encryptions differ yet both round-trip —
    guards against a fake 'encryption' that would be a stable encoding."""
    payload = b"same payload"
    blob_a, blob_b = dpapi_protect(payload), dpapi_protect(payload)
    assert blob_a != blob_b
    assert dpapi_unprotect(blob_a) == dpapi_unprotect(blob_b) == payload


def test_tampered_blob_fails_closed() -> None:
    blob = bytearray(dpapi_protect(b"integrity matters"))
    blob[len(blob) // 2] ^= 0xFF  # flip one byte mid-blob
    with pytest.raises(DpapiOperationError):
        dpapi_unprotect(bytes(blob))


def test_garbage_blob_fails_closed_never_returns_bytes() -> None:
    with pytest.raises(DpapiOperationError):
        dpapi_unprotect(b"not a dpapi blob at all")


def test_dpapi_error_message_carries_code_not_payload() -> None:
    """Fail-closed errors must not echo blob/payload bytes."""
    with pytest.raises(DpapiOperationError) as excinfo:
        dpapi_unprotect(b"garbage-blob-abcdef")
    assert "garbage-blob-abcdef" not in str(excinfo.value)
    assert "error code" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ProviderKeyStore: persistence contract on a throwaway path
# ---------------------------------------------------------------------------


@pytest.fixture()
def key_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProviderKeyStore:
    """A store on a tmp file, with all dev-fallback env vars cleared."""
    for env_var in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    return ProviderKeyStore(store_path=tmp_path / "keys.bin")


def test_set_get_delete_round_trip(key_store: ProviderKeyStore) -> None:
    assert key_store.get_key("groq") is None
    key_store.set_key("groq", SecretApiKey(FAKE_GROQ_KEY))
    stored = key_store.get_key("groq")
    assert stored is not None
    assert stored.reveal() == FAKE_GROQ_KEY
    key_store.delete_key("groq")
    assert key_store.get_key("groq") is None


def test_store_survives_reopening_persistence_is_real(tmp_path: Path) -> None:
    path = tmp_path / "keys.bin"
    ProviderKeyStore(store_path=path).set_key("gemini", SecretApiKey("fake-gemini-key-123"))
    reopened = ProviderKeyStore(store_path=path).get_key("gemini")
    assert reopened is not None
    assert reopened.reveal() == "fake-gemini-key-123"


def test_key_material_never_touches_disk_in_plaintext(tmp_path: Path) -> None:
    """The on-disk invariant itself: read keys.bin raw and prove neither the
    key value nor even the JSON field names are visible."""
    path = tmp_path / "keys.bin"
    ProviderKeyStore(store_path=path).set_key("groq", SecretApiKey(FAKE_GROQ_KEY))
    raw = path.read_bytes()
    assert FAKE_GROQ_KEY.encode() not in raw
    assert b'"groq"' not in raw  # structure is encrypted too


def test_multiple_keys_coexist_and_delete_is_surgical(key_store: ProviderKeyStore) -> None:
    key_store.set_key("groq", SecretApiKey("fake-groq-1"))
    key_store.set_key("gemini", SecretApiKey("fake-gemini-2"))
    key_store.set_key("anthropic", SecretApiKey("fake-anthropic-3"))
    assert key_store.keyed_providers() == {"groq", "gemini", "anthropic"}
    key_store.delete_key("gemini")
    assert key_store.keyed_providers() == {"groq", "anthropic"}
    groq = key_store.get_key("groq")
    assert groq is not None and groq.reveal() == "fake-groq-1"


def test_unknown_provider_is_refused(key_store: ProviderKeyStore) -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        key_store.set_key("openai", SecretApiKey("nope"))


def test_stored_key_beats_env_fallback(
    key_store: ProviderKeyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Precedence: a key the user saved in-app wins over a stale dev var."""
    monkeypatch.setenv("GROQ_API_KEY", "env-key-should-lose")
    key_store.set_key("groq", SecretApiKey("stored-key-should-win"))
    stored = key_store.get_key("groq")
    assert stored is not None
    assert stored.reveal() == "stored-key-should-win"


def test_env_fallback_applies_when_store_is_empty(
    key_store: ProviderKeyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    key = key_store.get_key("gemini")
    assert key is not None
    assert key.reveal() == "env-gemini-key"
    assert "gemini" in key_store.keyed_providers()


def test_whitespace_only_env_value_counts_as_no_key(
    key_store: ProviderKeyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank .env line must not fake a keyed provider (fail closed)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert key_store.get_key("anthropic") is None
    assert "anthropic" not in key_store.keyed_providers()


def test_corrupt_store_file_fails_loudly_not_as_empty(tmp_path: Path) -> None:
    """A tampered keys.bin must raise — silently treating it as 'no keys'
    would downgrade the user to un-keyed without telling them."""
    path = tmp_path / "keys.bin"
    path.write_bytes(b"corrupted garbage")
    with pytest.raises(DpapiOperationError):
        ProviderKeyStore(store_path=path).get_key("groq")


def test_atomic_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "keys.bin"
    store = ProviderKeyStore(store_path=path)
    store.set_key("groq", SecretApiKey("fake"))
    store.set_key("gemini", SecretApiKey("fake2"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "keys.bin"]
    assert leftovers == []


def test_store_blob_is_valid_json_after_decrypt(tmp_path: Path) -> None:
    """White-box: the decrypted blob is exactly the documented JSON shape."""
    path = tmp_path / "keys.bin"
    ProviderKeyStore(store_path=path).set_key("groq", SecretApiKey(FAKE_GROQ_KEY))
    decrypted = json.loads(dpapi_unprotect(path.read_bytes()))
    assert decrypted == {"groq": FAKE_GROQ_KEY}
