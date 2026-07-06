"""Adversarial rejection tests: every malformed frame must fail closed.

Inbound frames are untrusted input; ``parse_envelope`` is the trust
boundary. These tests enumerate the rejection matrix — wrong version,
missing/extra fields, wrong kinds, wrong types, oversized frames — and
assert the exact machine-readable error code for each.
"""

import json
from typing import Any

import pytest

from engine.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    ProtocolErrorCode,
    parse_envelope,
)


def _expect_rejection(raw: str | bytes, expected_code: ProtocolErrorCode) -> ProtocolError:
    """Assert the frame is rejected with exactly the expected code."""
    with pytest.raises(ProtocolError) as excinfo:
        parse_envelope(raw)
    assert excinfo.value.code == expected_code, (
        f"expected {expected_code}, got {excinfo.value.code}: {excinfo.value.message}"
    )
    return excinfo.value


def _valid_frame(**overrides: Any) -> dict[str, Any]:
    """A known-good frame; tests mutate exactly one aspect at a time."""
    frame: dict[str, Any] = {"v": 1, "kind": "command", "name": "ping", "id": "i1", "payload": {}}
    frame.update(overrides)
    return frame


# --- wrong protocol version -------------------------------------------------

@pytest.mark.parametrize("bad_version", [0, 2, -1, 999, "1", 1.5, None, [1], {"v": 1}])
def test_any_version_other_than_integer_1_is_rejected(bad_version: Any) -> None:
    _expect_rejection(json.dumps(_valid_frame(v=bad_version)), ProtocolErrorCode.INVALID_ENVELOPE)


# --- missing / extra fields --------------------------------------------------

@pytest.mark.parametrize("missing", ["v", "kind", "name", "id", "payload"])
def test_each_missing_required_field_is_rejected(missing: str) -> None:
    frame = _valid_frame()
    del frame[missing]
    error = _expect_rejection(json.dumps(frame), ProtocolErrorCode.INVALID_ENVELOPE)
    assert missing in error.message  # the error names the offending field


def test_unknown_extra_top_level_field_is_rejected_deny_by_default() -> None:
    _expect_rejection(
        json.dumps(_valid_frame(injected="evil")), ProtocolErrorCode.INVALID_ENVELOPE
    )


def test_empty_object_is_rejected() -> None:
    _expect_rejection("{}", ProtocolErrorCode.INVALID_ENVELOPE)


# --- wrong kinds --------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_kind", ["EVENT", "Command", "request", "", "ping", 1, None, ["command"]]
)
def test_kinds_outside_the_pinned_three_are_rejected(bad_kind: Any) -> None:
    _expect_rejection(json.dumps(_valid_frame(kind=bad_kind)), ProtocolErrorCode.INVALID_ENVELOPE)


# --- wrong field types / degenerate values ------------------------------------

@pytest.mark.parametrize("bad_name", ["", "x" * 129, 42, None, {"n": 1}])
def test_degenerate_name_values_are_rejected(bad_name: Any) -> None:
    """Empty, over-length (129 > 128 boundary), and non-string names all fail."""
    _expect_rejection(json.dumps(_valid_frame(name=bad_name)), ProtocolErrorCode.INVALID_ENVELOPE)


@pytest.mark.parametrize("bad_id", ["", "x" * 129, 7, None])
def test_degenerate_id_values_are_rejected(bad_id: Any) -> None:
    _expect_rejection(json.dumps(_valid_frame(id=bad_id)), ProtocolErrorCode.INVALID_ENVELOPE)


@pytest.mark.parametrize("bad_payload", ["text", 1, None, [1, 2], True])
def test_non_object_payloads_are_rejected(bad_payload: Any) -> None:
    _expect_rejection(
        json.dumps(_valid_frame(payload=bad_payload)), ProtocolErrorCode.INVALID_ENVELOPE
    )


# --- not JSON / not an object --------------------------------------------------

@pytest.mark.parametrize(
    "garbage",
    ["", "not json", "{truncated", '{"v":1,', "\x00\x01\x02", "NaN}", '{"v": 1}]'],
)
def test_non_json_garbage_is_rejected_as_invalid_json(garbage: str) -> None:
    _expect_rejection(garbage, ProtocolErrorCode.INVALID_JSON)


@pytest.mark.parametrize("non_object", ["[]", '"a string"', "42", "null", "true"])
def test_valid_json_that_is_not_an_object_is_rejected(non_object: str) -> None:
    _expect_rejection(non_object, ProtocolErrorCode.INVALID_ENVELOPE)


# --- oversized frames (boundary-exact) -----------------------------------------

def test_frame_one_byte_over_the_limit_is_rejected_before_json_parsing() -> None:
    """Just-over boundary: MAX + 1 bytes must be refused, even though the
    at-limit twin (see roundtrip suite) is accepted."""
    oversized = "x" * (MAX_MESSAGE_BYTES + 1)  # not even JSON — cap fires first
    _expect_rejection(oversized, ProtocolErrorCode.MESSAGE_TOO_LARGE)


def test_oversized_valid_json_is_still_rejected_by_the_byte_cap() -> None:
    frame = _valid_frame(payload={"pad": "x" * MAX_MESSAGE_BYTES})
    _expect_rejection(json.dumps(frame), ProtocolErrorCode.MESSAGE_TOO_LARGE)


def test_oversized_bytes_input_is_measured_in_bytes_not_characters() -> None:
    """Multi-byte UTF-8: character count under the limit must not evade the
    byte cap (each snowman is 3 bytes)."""
    snowmen = "☃" * ((MAX_MESSAGE_BYTES // 3) + 1)
    assert len(snowmen) < MAX_MESSAGE_BYTES  # chars under, bytes over
    _expect_rejection(snowmen, ProtocolErrorCode.MESSAGE_TOO_LARGE)


# --- rejection must not reflect payload content ---------------------------------

def test_rejection_message_does_not_echo_payload_contents() -> None:
    """Injection defence: hostile payload strings must not be reflected in
    the error message."""
    marker = "EVIL_REFLECTED_MARKER_9000"
    error = _expect_rejection(
        json.dumps(_valid_frame(v=2, payload={"attack": marker})),
        ProtocolErrorCode.INVALID_ENVELOPE,
    )
    assert marker not in error.message
