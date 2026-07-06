"""Device-change recovery: the 'silent capture but device vanished' class.

Drives the DualStreamCaptureController against a scripted fake backend:
default-device switches and dead streams must be detected and reopened
within the 1 s budget, the recovery callback must fire with honest
numbers, audio must flow (resampled + labelled) into the ring buffer, and
a failed stream open at start must tear everything down (fail closed).
"""

import asyncio
from collections.abc import Callable

import numpy as np
import pytest

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import (
    CaptureDeviceSpec,
    DualStreamCaptureController,
)
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer

FAST_POLL_S = 0.03  # Fast watchdog so tests finish in tens of ms.


class FakeStreamHandle:
    def __init__(self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]) -> None:
        self.spec = spec
        self.on_chunk = on_chunk
        self.closed = False
        self.alive = True

    @property
    def is_alive(self) -> bool:
        return self.alive and not self.closed

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    """Scripted backend: tests mutate ``specs`` to simulate default changes."""

    def __init__(self) -> None:
        self.specs: dict[StreamLabel, CaptureDeviceSpec] = {
            StreamLabel.THEM: CaptureDeviceSpec("3:Speakers", "Speakers", 48_000, 2),
            StreamLabel.ME: CaptureDeviceSpec("1:Mic", "Mic", 44_100, 1),
        }
        self.open_handles: list[FakeStreamHandle] = []
        self.fail_open_for: set[str] = set()  # Spec keys whose open must fail.
        self.probe_error_once: set[StreamLabel] = set()

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        if stream in self.probe_error_once:
            self.probe_error_once.discard(stream)
            raise OSError("device list churning")
        return self.specs[stream]

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> FakeStreamHandle:
        if spec.key in self.fail_open_for:
            raise OSError(f"cannot open {spec.key}")
        handle = FakeStreamHandle(spec, on_chunk)
        self.open_handles.append(handle)
        return handle

    def live_handle(self, label: StreamLabel) -> FakeStreamHandle:
        matching = [
            h for h in self.open_handles if h.spec == self.specs[label] and not h.closed
        ]
        assert matching, f"no live handle for {label}"
        return matching[-1]


async def test_start_opens_both_streams_and_stop_closes_them() -> None:
    backend = FakeBackend()
    controller = DualStreamCaptureController(
        backend, TimestampedAudioRingBuffer(), poll_interval_s=FAST_POLL_S
    )
    await controller.start()
    assert len(backend.open_handles) == 2
    assert controller.device_names == {"them": "Speakers", "me": "Mic"}
    await controller.stop()
    assert all(handle.closed for handle in backend.open_handles)


async def test_audio_chunks_are_resampled_labelled_and_timestamped() -> None:
    backend = FakeBackend()
    ring = TimestampedAudioRingBuffer()
    controller = DualStreamCaptureController(backend, ring, poll_interval_s=FAST_POLL_S)
    await controller.start()
    try:
        # 0.1 s of 48 kHz stereo int16 through the "them" callback.
        mic_chunk = np.full(4800 * 2, 8000, dtype=np.int16).tobytes()
        backend.live_handle(StreamLabel.THEM).on_chunk(mic_chunk, 123.456)
        frames = ring.drain()
        assert frames and all(f.stream is StreamLabel.THEM for f in frames)
        total = sum(f.samples.size for f in frames)
        assert 0 < total <= 1600  # 0.1 s at 16 kHz (resampler may buffer a tail).
        # Timestamp arithmetic: t_start = callback end time - duration.
        first = frames[0]
        assert first.t_start_monotonic == pytest.approx(
            123.456 - first.samples.size / 16_000
        )
    finally:
        await controller.stop()


async def test_default_device_change_recovers_within_the_1s_budget() -> None:
    backend = FakeBackend()
    changes: list[tuple[StreamLabel, str, float]] = []
    controller = DualStreamCaptureController(
        backend,
        TimestampedAudioRingBuffer(),
        on_device_changed=lambda label, name, ms: changes.append((label, name, ms)),
        poll_interval_s=FAST_POLL_S,
    )
    await controller.start()
    try:
        old_handle = backend.live_handle(StreamLabel.THEM)
        # The user plugs in a headset: default render endpoint changes.
        backend.specs[StreamLabel.THEM] = CaptureDeviceSpec("7:Headset", "Headset", 44_100, 2)
        deadline = asyncio.get_running_loop().time() + 1.0  # The 1 s requirement.
        while not changes and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert changes, "device change was not recovered within 1 s"
        label, name, recovered_ms = changes[0]
        assert label is StreamLabel.THEM
        assert name == "Headset"
        assert 0 <= recovered_ms < 1000
        assert old_handle.closed  # Old endpoint released.
        assert backend.live_handle(StreamLabel.THEM).spec.name == "Headset"
        assert controller.device_names["them"] == "Headset"
    finally:
        await controller.stop()


async def test_dead_stream_same_device_key_is_reopened() -> None:
    """Silent-capture case: the device is still 'default' but the stream
    died (driver stall). Liveness, not just identity, must be watched."""
    backend = FakeBackend()
    changes: list[tuple[StreamLabel, str, float]] = []
    controller = DualStreamCaptureController(
        backend,
        TimestampedAudioRingBuffer(),
        on_device_changed=lambda label, name, ms: changes.append((label, name, ms)),
        poll_interval_s=FAST_POLL_S,
    )
    await controller.start()
    try:
        backend.live_handle(StreamLabel.ME).alive = False  # Stream dies silently.
        await asyncio.sleep(FAST_POLL_S * 5)
        assert changes and changes[0][0] is StreamLabel.ME
        assert backend.live_handle(StreamLabel.ME).is_alive  # Fresh stream flowing.
    finally:
        await controller.stop()


async def test_transient_probe_failure_does_not_kill_the_watchdog() -> None:
    backend = FakeBackend()
    changes: list[tuple[StreamLabel, str, float]] = []
    controller = DualStreamCaptureController(
        backend,
        TimestampedAudioRingBuffer(),
        on_device_changed=lambda label, name, ms: changes.append((label, name, ms)),
        poll_interval_s=FAST_POLL_S,
    )
    await controller.start()
    try:
        backend.probe_error_once.add(StreamLabel.THEM)  # One bad probe tick...
        backend.specs[StreamLabel.THEM] = CaptureDeviceSpec("9:Dock", "Dock", 48_000, 2)
        await asyncio.sleep(FAST_POLL_S * 8)  # ...must not stop later recovery.
        assert changes and changes[0][1] == "Dock"
    finally:
        await controller.stop()


async def test_failed_stream_open_at_start_tears_everything_down() -> None:
    """Fail closed: if the mic cannot open, the loopback must not keep
    capturing half a meeting silently."""
    backend = FakeBackend()
    backend.fail_open_for.add("1:Mic")
    controller = DualStreamCaptureController(
        backend, TimestampedAudioRingBuffer(), poll_interval_s=FAST_POLL_S
    )
    with pytest.raises(OSError, match="cannot open"):
        await controller.start()
    assert all(handle.closed for handle in backend.open_handles)  # No orphans.


async def test_double_start_fails_closed() -> None:
    backend = FakeBackend()
    controller = DualStreamCaptureController(
        backend, TimestampedAudioRingBuffer(), poll_interval_s=FAST_POLL_S
    )
    await controller.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            await controller.start()
    finally:
        await controller.stop()


async def test_stop_is_idempotent() -> None:
    backend = FakeBackend()
    controller = DualStreamCaptureController(
        backend, TimestampedAudioRingBuffer(), poll_interval_s=FAST_POLL_S
    )
    await controller.start()
    await controller.stop()
    await controller.stop()  # Second stop must be a harmless no-op.
