"""Read-only enumeration of this machine's WASAPI audio endpoints.

Purpose: back the ``devices.list`` command with the REAL device inventory —
microphones (the Me stream candidates) and render endpoints observed via
their WASAPI loopback twins (the Them stream) — using the same
pyaudiowpatch backend the capture path already runs on. Additive helper:
the capture backend itself is untouched.
Pipeline position: called (off the event loop) by
``engine.audio.devices_list_command_dispatcher``.

Security invariants:
- Read-only observation: enumerates endpoints, opens nothing, records
  nothing (local-only invariant — names only ever cross the loopback WS).
- Fresh PyAudio instance per listing, terminated in ``finally`` — the same
  no-orphaned-PortAudio-refs discipline as the capture backend's probes.
"""

import contextlib
import logging
from typing import Any

from engine.protocol.device_listing_payloads import (
    DEVICE_KIND_CAPTURE,
    DEVICE_KIND_RENDER,
    AudioDeviceDescription,
)

logger = logging.getLogger(__name__)


def _device_id(info: dict[str, Any]) -> str:
    """Same ``index:name`` identity scheme as the capture backend's keys."""
    return f"{info['index']}:{info['name']}"


def list_audio_devices() -> list[AudioDeviceDescription]:
    """Enumerate WASAPI endpoints as typed descriptions (blocking; thread it).

    Loopback devices represent RENDER endpoints (what "system audio" can
    follow); non-loopback input devices are CAPTURE endpoints (microphones).
    Non-WASAPI host APIs (MME/DirectSound duplicates of the same hardware)
    are excluded so each physical endpoint appears once.

    Raises on an unavailable audio subsystem — the dispatcher surfaces that
    as an honest error reply (fail closed, never a fabricated list).
    """
    import pyaudiowpatch as pyaudio  # Lazy: Windows-only dependency.

    instance = pyaudio.PyAudio()  # Fresh instance -> fresh device topology view.
    try:
        wasapi_index = int(instance.get_host_api_info_by_type(pyaudio.paWASAPI)["index"])
        # Defaults are best-effort: a machine with no default mic must still
        # list its render endpoints (and vice versa) — degrade, never crash.
        default_capture_id: str | None = None
        with contextlib.suppress(OSError):
            default_capture_id = _device_id(dict(instance.get_default_input_device_info()))
        default_render_id: str | None = None
        with contextlib.suppress(OSError, LookupError):
            default_render_id = _device_id(dict(instance.get_default_wasapi_loopback()))

        devices: list[AudioDeviceDescription] = []
        for index in range(instance.get_device_count()):
            info = dict(instance.get_device_info_by_index(index))
            if int(info.get("hostApi", -1)) != wasapi_index:
                continue  # one entry per endpoint: WASAPI view only
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue  # plain output halves are covered by their loopback twin
            is_loopback = bool(info.get("isLoopbackDevice", False))
            device_id = _device_id(info)
            default_id = default_render_id if is_loopback else default_capture_id
            devices.append(
                AudioDeviceDescription(
                    id=device_id,
                    name=str(info["name"]),
                    kind=DEVICE_KIND_RENDER if is_loopback else DEVICE_KIND_CAPTURE,
                    is_default=device_id == default_id,
                )
            )
        return devices
    finally:
        instance.terminate()
