"""Names + payloads for the ``devices.list`` command (WS protocol v1).

Purpose: the pinned wire shape by which the Settings screen reads this
machine's real audio endpoints — retiring the UI's mock device names. The
ENUMERATION lives in ``engine.audio.audio_device_listing``; this module is
only the typed vocabulary and the reply payload builder.
Pipeline position: between ``engine.audio.devices_list_command_dispatcher``
and the UI's TypeScript mirror.

Security invariant: the command payload is strictly validated (deliberately
empty, unknown fields rejected — deny by default); the reply carries device
NAMES only over the loopback-bound socket (local-only invariant).
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

COMMAND_DEVICES_LIST = "devices.list"

# The two endpoint kinds the product cares about: microphones ("capture",
# the Me stream) and render endpoints tapped via WASAPI loopback ("render",
# the Them stream).
DEVICE_KIND_CAPTURE = "capture"
DEVICE_KIND_RENDER = "render"


class DevicesListCommandPayload(BaseModel):
    """Payload of ``devices.list`` — deliberately empty."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class AudioDeviceDescription:
    """One enumerated audio endpoint, exactly as the UI renders it.

    ``id`` uses the same ``"{index}:{name}"`` identity scheme as the capture
    backend's device keys, so a future device-picker can hand it straight
    back to the audio layer.
    """

    id: str
    name: str
    kind: str  # DEVICE_KIND_CAPTURE | DEVICE_KIND_RENDER
    is_default: bool

    def __post_init__(self) -> None:
        # Fail closed: an unknown kind must never reach the wire.
        if self.kind not in (DEVICE_KIND_CAPTURE, DEVICE_KIND_RENDER):
            raise ValueError(f"kind must be capture|render, got {self.kind!r}")


def build_devices_list_payload(devices: list[AudioDeviceDescription]) -> dict[str, Any]:
    """The ``devices.list`` ok-reply payload: ``{"devices": [...]}``."""
    return {
        "devices": [
            {
                "id": device.id,
                "name": device.name,
                "kind": device.kind,
                "is_default": device.is_default,
            }
            for device in devices
        ]
    }
