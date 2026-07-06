"""Envelope model, parsing, and error replies for WS protocol v1.

Purpose: defines the single wire shape every frame must have —
``{"v": 1, "kind": "event"|"command"|"reply", "name": str, "id": str,
"payload": dict}`` — plus the fail-closed parser and the standard error
reply used when a frame is rejected.
Pipeline position: first stop for every inbound WebSocket frame; last stop
(serialisation) for every outbound one.

Security invariants:
- Inbound frames are untrusted: parsing enforces a hard byte cap BEFORE
  JSON decoding (resource-exhaustion defence) and strict field validation
  (unknown fields rejected) — deny by default.
- A rejected frame yields a structured ``error`` reply; it never raises
  past the handler and never crashes the socket (fail closed, stay up).
"""

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Protocol version pinned by contract with the UI.
PROTOCOL_VERSION = 1

# Hard cap on a single inbound frame, enforced before JSON parsing.
# WHY 64 KiB: commands are small control messages; anything larger is either
# a bug or an abuse attempt (resource-exhaustion defence — deny by default).
MAX_MESSAGE_BYTES = 64 * 1024

# Bounds on identifier-ish strings: non-empty, sane maximum, so a hostile
# frame cannot smuggle megabytes through `name`/`id` either.
_MAX_NAME_LENGTH = 128
_MAX_ID_LENGTH = 128


class EnvelopeKind(StrEnum):
    """The three legal frame kinds in protocol v1."""

    EVENT = "event"
    COMMAND = "command"
    REPLY = "reply"


class ProtocolErrorCode(StrEnum):
    """Stable machine-readable error codes carried in `error` replies."""

    INVALID_JSON = "invalid_json"
    INVALID_ENVELOPE = "invalid_envelope"
    MESSAGE_TOO_LARGE = "message_too_large"
    NOT_A_COMMAND = "not_a_command"
    UNKNOWN_COMMAND = "unknown_command"
    # M1 additions (additive — existing codes/semantics unchanged):
    INVALID_PAYLOAD = "invalid_payload"  # Command payload failed validation.
    CAPTURE_ERROR = "capture_error"  # Capture could not start/stop.


class ProtocolError(Exception):
    """Raised when an inbound frame violates the protocol.

    Carries the stable error code and a human-readable message; the server
    converts it into an `error` reply instead of letting it propagate.
    """

    def __init__(self, code: ProtocolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Envelope(BaseModel):
    """The pinned protocol v1 envelope. The UI depends on this exact shape.

    ``extra="forbid"``: unknown top-level fields are rejected — deny by
    default, so typos and injected fields fail loudly instead of silently.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Literal pin: only the INTEGER 1 is accepted — strict mode rejects
    # "1" (string) and 1.0 (float); versioning must be unambiguous.
    v: int = Field(ge=PROTOCOL_VERSION, le=PROTOCOL_VERSION, strict=True)
    kind: EnvelopeKind
    name: str = Field(min_length=1, max_length=_MAX_NAME_LENGTH)
    id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    payload: dict[str, Any]

    def to_wire(self) -> str:
        """Serialise for the wire. Compact separators keep frames small."""
        return json.dumps(self.model_dump(mode="json"), separators=(",", ":"))


def parse_envelope(raw: str | bytes) -> Envelope:
    """Parse and validate one untrusted inbound frame, fail-closed.

    Order matters for safety: size cap first (cheap, before any decode),
    then JSON decode, then strict model validation.

    Raises ``ProtocolError`` with a stable code on any violation.
    """
    # Injection/exhaustion defence: cap bytes BEFORE decoding untrusted input.
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if size > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            ProtocolErrorCode.MESSAGE_TOO_LARGE,
            f"frame is {size} bytes; the limit is {MAX_MESSAGE_BYTES}",
        )
    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(ProtocolErrorCode.INVALID_JSON, f"not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ProtocolError(
            ProtocolErrorCode.INVALID_ENVELOPE, "top-level JSON value must be an object"
        )
    try:
        return Envelope.model_validate(decoded)
    except ValidationError as exc:
        # Summarise which fields failed without echoing payload contents back
        # (untrusted input is not reflected verbatim — injection defence).
        failed = sorted({str(err["loc"][0]) if err["loc"] else "<root>" for err in exc.errors()})
        raise ProtocolError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            f"envelope validation failed on field(s): {', '.join(failed)}",
        ) from exc


def error_reply(reply_id: str, code: ProtocolErrorCode, message: str) -> Envelope:
    """Build the standard `error` reply for a rejected or unknown command.

    ``reply_id`` echoes the offending frame's id when one could be
    extracted, so the UI can correlate; callers pass a fresh id otherwise.
    """
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": code.value, "message": message},
    )
