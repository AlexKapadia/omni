"""Payload models + event names for capture/transcript WS messages (v1).

Purpose: the pinned shapes of every M1 addition to protocol v1 — the
``capture.start`` / ``capture.stop`` commands and the
``capture.started`` / ``capture.stopped`` / ``capture.device_changed`` /
``transcript.partial`` / ``transcript.final`` events. The UI's TypeScript
mirror is built against these exact field names; changes are breaking.
Pipeline position: between ``engine.stt.live_capture_service`` (producer)
and ``engine.protocol.websocket_envelope`` (wire form).

Security invariant: payloads carry transcript text and device names ONLY
over the loopback-bound WebSocket to the local UI — nothing here reaches
the network (local-only invariant). Command payloads are validated
strictly (unknown fields rejected — deny by default).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- message names (TS-mirror-compatible, dot-namespaced like `engine.heartbeat`).
COMMAND_CAPTURE_START = "capture.start"
COMMAND_CAPTURE_STOP = "capture.stop"
EVENT_CAPTURE_STARTED = "capture.started"
EVENT_CAPTURE_STOPPED = "capture.stopped"
EVENT_CAPTURE_DEVICE_CHANGED = "capture.device_changed"
EVENT_TRANSCRIPT_PARTIAL = "transcript.partial"
EVENT_TRANSCRIPT_FINAL = "transcript.final"


class CaptureStartCommandPayload(BaseModel):
    """Payload of the ``capture.start`` command (client -> engine).

    ``extra="forbid"``: unknown fields in a command are rejected — deny by
    default, same discipline as the envelope itself.
    """

    model_config = ConfigDict(extra="forbid")

    # Optional human title for the meeting row; bounded so a hostile client
    # cannot stuff megabytes into the DB through one field.
    title: str | None = Field(default=None, max_length=512)


class CaptureStopCommandPayload(BaseModel):
    """Payload of the ``capture.stop`` command — deliberately empty."""

    model_config = ConfigDict(extra="forbid")


def build_capture_started_payload(meeting_id: str, reason: str) -> dict[str, Any]:
    """``capture.started`` event: capture is live for ``meeting_id``."""
    return {"meeting_id": meeting_id, "reason": reason}


def build_capture_stopped_payload(meeting_id: str, reason: str) -> dict[str, Any]:
    """``capture.stopped`` event: ``reason`` is 'command', 'silence', or 'error'."""
    return {"meeting_id": meeting_id, "reason": reason}


def build_capture_device_changed_payload(device_name: str, recovered_ms: float) -> dict[str, Any]:
    """``capture.device_changed``: default endpoint moved; capture recovered.

    ``recovered_ms`` is the measured close-old -> open-new time (speed is
    a showcase: recovery is instrumented, not asserted).
    """
    return {"device_name": device_name, "recovered_ms": recovered_ms}


def build_transcript_partial_payload(
    stream: str,
    text: str,
    t_start: float,
    t_end: float,
    seq: int,
    *,
    speaker_id: str,
    speaker_label: str,
) -> dict[str, Any]:
    """``transcript.partial``: live in-progress text for one open segment."""
    return {
        "stream": stream,
        "text": text,
        "t_start": t_start,
        "t_end": t_end,
        "seq": seq,
        "speaker_id": speaker_id,
        "speaker_label": speaker_label,
    }


def build_transcript_final_payload(
    stream: str,
    text: str,
    t_start: float,
    t_end: float,
    seq: int,
    segment_id: str,
    lag_ms: float,
    *,
    speaker_id: str,
    speaker_label: str,
) -> dict[str, Any]:
    """``transcript.final``: one persisted segment, verbatim model text."""
    return {
        "stream": stream,
        "text": text,
        "t_start": t_start,
        "t_end": t_end,
        "seq": seq,
        "segment_id": segment_id,
        "lag_ms": lag_ms,
        "speaker_id": speaker_id,
        "speaker_label": speaker_label,
    }
