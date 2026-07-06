"""Names + payloads for the M6 detection surface (WS protocol v1, additive).

Purpose: the pinned wire shapes for bot-free meeting detection —
``meeting.detected`` / ``capture.suggest_stop`` events flowing engine -> UI
and the ``detection.dismiss`` command flowing UI -> engine. The decision
LOGIC lives in ``engine.detect``; this module is only the wire vocabulary,
mirroring ``capture_event_payloads``.
Pipeline position: between ``engine.detection_server_wiring`` (producer /
dispatcher) and the UI's TypeScript mirror.

Security invariants:
- ``detection.dismiss`` is strictly validated (unknown fields rejected,
  bounded key) — deny by default like every inbound command.
- Events only ever SUGGEST; the actual capture start/stop stays behind the
  existing user-driven command path (approval-before-execute).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- message names (pinned, dot-namespaced like "capture.started") ---
EVENT_MEETING_DETECTED = "meeting.detected"
EVENT_CAPTURE_SUGGEST_STOP = "capture.suggest_stop"
COMMAND_DETECTION_DISMISS = "detection.dismiss"


class DetectionDismissCommandPayload(BaseModel):
    """Payload of ``detection.dismiss`` — the user said "no" to a card."""

    model_config = ConfigDict(extra="forbid")

    # Bounded identifier: dedupe keys are engine-issued source strings, so a
    # sane cap rejects smuggled bulk content without constraining real keys.
    dedupe_key: str = Field(min_length=1, max_length=128)


def build_meeting_detected_payload(
    source: str,
    reason: str,
    confidence: float,
    dedupe_key: str | None = None,
    auto_start: bool = False,
) -> dict[str, Any]:
    """``meeting.detected``: a meeting was noticed without joining anything.

    ``dedupe_key`` (suggestions only) is what ``detection.dismiss`` echoes
    back; ``auto_start`` is present-and-true ONLY for the user-opted-in
    auto-start path (deny by default — absent means "suggestion card").
    """
    payload: dict[str, Any] = {"source": source, "reason": reason, "confidence": confidence}
    if dedupe_key is not None:
        payload["dedupe_key"] = dedupe_key
    if auto_start:
        payload["auto_start"] = True
    return payload


def build_capture_suggest_stop_payload(reason: str) -> dict[str, Any]:
    """``capture.suggest_stop``: the meeting looks over while capture runs."""
    return {"reason": reason}
