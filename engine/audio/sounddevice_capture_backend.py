"""Cross-platform capture via sounddevice (macOS + Linux)."""

from __future__ import annotations

import importlib
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec, CaptureStreamHandle

logger = logging.getLogger(__name__)

_CHUNK_SECONDS = 0.02


def _sounddevice() -> Any:
    """Lazy import so mypy does not require a sounddevice stub."""
    return importlib.import_module("sounddevice")


def _find_loopback_device_index() -> int | None:
    sd = _sounddevice()

    devices = sd.query_devices()
    default_output = sd.default.device[1]
    default_output_name = ""
    if default_output is not None and default_output >= 0:
        default_output_name = str(devices[default_output].get("name", "")).lower()

    for index, device in enumerate(devices):
        name = str(device.get("name", "")).lower()
        if int(device.get("max_input_channels", 0)) < 1:
            continue
        if "blackhole" in name or "soundflower" in name or "loopback" in name:
            return index
        if "monitor of" in name and (
            not default_output_name or default_output_name.split()[0] in name
        ):
            return index
    for index, device in enumerate(devices):
        name = str(device.get("name", "")).lower()
        if int(device.get("max_input_channels", 0)) < 1:
            continue
        if "monitor" in name:
            return index
    return None


class _SoundDeviceStreamHandle:
    """Callback stream with a drain thread into the controller contract."""

    def __init__(
        self,
        stream: object,
        frame_queue: queue.Queue[tuple[bytes, float]],
        on_chunk: Callable[[bytes, float], None],
    ) -> None:
        self._stream = stream
        self._closed = False
        self._thread = threading.Thread(
            target=self._drain,
            args=(frame_queue, on_chunk),
            daemon=True,
            name="sounddevice-capture-drain",
        )
        self._thread.start()

    def _drain(
        self,
        frame_queue: queue.Queue[tuple[bytes, float]],
        on_chunk: Callable[[bytes, float], None],
    ) -> None:
        while not self._closed:
            try:
                data, timestamp = frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            on_chunk(data, timestamp)

    @property
    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(getattr(self._stream, "active", False))
        except Exception:
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        stop = getattr(self._stream, "stop", None)
        close = getattr(self._stream, "close", None)
        try:
            if callable(stop):
                stop()
            if callable(close):
                close()
        except Exception:
            logger.debug("sounddevice stream close failed", exc_info=True)


class SoundDeviceCaptureBackend:
    """Capture microphone + monitor/loopback devices on macOS and Linux."""

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        sd = _sounddevice()

        if stream is StreamLabel.ME:
            device_index = sd.default.device[0]
            if device_index is None or int(device_index) < 0:
                raise RuntimeError("no default microphone found")
        else:
            device_index = _find_loopback_device_index()
            if device_index is None:
                raise RuntimeError(
                    "no system-audio loopback device found — on Linux enable PipeWire/Pulse "
                    "monitor capture; on macOS install BlackHole and route system audio"
                )
        info = sd.query_devices(device_index)
        return CaptureDeviceSpec(
            key=f"{device_index}:{info['name']}",
            name=str(info["name"]),
            sample_rate=int(info["default_samplerate"]),
            channels=max(1, min(int(info["max_input_channels"]), 2)),
        )

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        """Look up an input by ``"{index}:{name}"`` — fail closed on miss."""
        sd = _sounddevice()

        try:
            device_index = int(key.split(":", 1)[0])
        except (ValueError, IndexError) as exc:
            raise LookupError(f"invalid mic device key: {key!r}") from exc
        try:
            info = sd.query_devices(device_index)
        except Exception as exc:
            raise LookupError(f"could not resolve mic device {key!r}: {exc}") from exc
        if int(info.get("max_input_channels", 0)) < 1:
            raise LookupError(f"device {key!r} is not an input device")
        return CaptureDeviceSpec(
            key=f"{device_index}:{info['name']}",
            name=str(info["name"]),
            sample_rate=int(info["default_samplerate"]),
            channels=max(1, min(int(info["max_input_channels"]), 2)),
        )

    def open_capture_stream(
        self,
        spec: CaptureDeviceSpec,
        on_chunk: Callable[[bytes, float], None],
    ) -> CaptureStreamHandle:
        sd = _sounddevice()

        device_index = int(spec.key.split(":", 1)[0])
        frames_per_buffer = max(128, int(spec.sample_rate * _CHUNK_SECONDS))
        frame_queue: queue.Queue[tuple[bytes, float]] = queue.Queue()

        def callback(
            indata: Any, _frames: Any, _time_info: Any, status: Any
        ) -> None:
            if status:
                logger.warning("sounddevice capture status: %s", status)
            mono = indata[:, 0] if getattr(indata, "ndim", 1) > 1 else indata
            pcm16 = (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)
            frame_queue.put((pcm16.tobytes(), time.monotonic()))

        stream = sd.InputStream(
            device=device_index,
            channels=spec.channels,
            samplerate=spec.sample_rate,
            dtype="float32",
            blocksize=frames_per_buffer,
            callback=callback,
        )
        stream.start()
        return _SoundDeviceStreamHandle(stream, frame_queue, on_chunk)
