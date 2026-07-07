"""M7 model download: additive progress + sha256 integrity, and the surface.

Adversarial coverage of ``download_models_with_progress`` (no network — an
injected fetch writes synthetic bytes): progress beats stream during the
download; sha256 verifies True only against the pinned manifest; a hash
MISMATCH deletes the corrupt file and raises (fail closed); an unpinned file
is completed but reported unverified. The ``models.download`` dispatcher then
runs it off the reply path and streams progress/completed/failed events, and
single-flights concurrent requests.
"""

import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from engine.protocol import (
    EVENT_MODELS_DOWNLOAD_COMPLETED,
    EVENT_MODELS_DOWNLOAD_FAILED,
    EVENT_MODELS_DOWNLOAD_PROGRESS,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
)
from engine.stt.model_weights_downloader import (
    ModelIntegrityError,
    ModelSpec,
    download_models_with_progress,
)
from engine.wiring.models_download_command_dispatcher import (
    ModelsDownloadCommandGateway,
    dispatch_models_command,
)

_BYTES = b"synthetic-model-weights-payload" * 4
_SHA = hashlib.sha256(_BYTES).hexdigest()
_SPEC = ModelSpec(filename="tiny.bin", url="https://example.test/tiny.bin", description="tiny")


def _fetch_ok(url: str, destination: Path, progress) -> None:  # type: ignore[no-untyped-def]
    # Emulate a streamed download with two progress beats.
    half = len(_BYTES) // 2
    destination.write_bytes(_BYTES)
    progress(half, len(_BYTES))
    progress(len(_BYTES), len(_BYTES))


def _manifest(tmp_path: Path, sha: str) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"models": [{"name": "tiny.bin", "sha256": sha}]}), encoding="utf-8")
    return path


def test_progress_streams_and_sha256_verifies_on_match(tmp_path: Path) -> None:
    beats: list[tuple[str, int, int | None, bool | None]] = []
    results = download_models_with_progress(
        lambda f, r, t, v: beats.append((f, r, t, v)),
        models_dir=tmp_path / "models",
        specs=(_SPEC,),
        manifest_path=_manifest(tmp_path, _SHA),
        fetch=_fetch_ok,
    )
    assert results[0]["sha256_verified"] is True
    assert results[0]["sha256"] == _SHA
    # A mid-download beat (verification unknown) precedes the verified final beat.
    assert any(v is None for _, _, _, v in beats)
    assert beats[-1][3] is True


def test_hash_mismatch_deletes_file_and_raises(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    with pytest.raises(ModelIntegrityError) as excinfo:
        download_models_with_progress(
            lambda *_: None,
            models_dir=models_dir,
            specs=(_SPEC,),
            manifest_path=_manifest(tmp_path, "0" * 64),  # wrong pin
            fetch=_fetch_ok,
        )
    assert excinfo.value.filename == "tiny.bin"
    # Fail closed: the corrupt file is gone so a retry re-fetches clean.
    assert not (models_dir / "tiny.bin").exists()


def test_unpinned_file_completes_but_is_unverified(tmp_path: Path) -> None:
    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text(json.dumps({"models": []}), encoding="utf-8")
    results = download_models_with_progress(
        lambda *_: None,
        models_dir=tmp_path / "models",
        specs=(_SPEC,),
        manifest_path=empty_manifest,
        fetch=_fetch_ok,
    )
    # No pin => cannot positively verify => honest False, never a guessed True.
    assert results[0]["sha256_verified"] is False


def test_present_file_is_reverified_not_refetched(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "tiny.bin").write_bytes(_BYTES)
    calls = {"n": 0}

    def _fetch_should_not_run(url: str, dest: Path, progress) -> None:  # type: ignore[no-untyped-def]
        calls["n"] += 1

    results = download_models_with_progress(
        lambda *_: None,
        models_dir=models_dir,
        specs=(_SPEC,),
        manifest_path=_manifest(tmp_path, _SHA),
        fetch=_fetch_should_not_run,
    )
    assert calls["n"] == 0  # present file is hashed, never re-downloaded
    assert results[0]["sha256_verified"] is True


class _CapturingHub(EventBroadcastHub):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_event(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append((name, payload))
        await super().broadcast_event(name, payload)


async def test_dispatcher_streams_completed_event_with_verified_files(tmp_path: Path) -> None:
    hub = _CapturingHub()
    gateway = ModelsDownloadCommandGateway(
        hub=hub,
        models_dir=tmp_path / "models",
        manifest_path=_manifest(tmp_path, _SHA),
        fetch=_fetch_ok,
        specs=(_SPEC,),
    )
    send_replies: list[Envelope] = []

    async def send(env: Envelope) -> None:
        send_replies.append(env)

    command = Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="models.download", id=str(uuid.uuid4()), payload={}
    )
    await dispatch_models_command(command, gateway, send)
    assert send_replies[0].name == "ok"  # accepted immediately
    assert gateway._task is not None
    await gateway._task  # let the background download finish (do NOT cancel)
    names = [name for name, _ in hub.events]
    assert EVENT_MODELS_DOWNLOAD_PROGRESS in names
    assert EVENT_MODELS_DOWNLOAD_COMPLETED in names
    assert EVENT_MODELS_DOWNLOAD_FAILED not in names
    completed = next(p for n, p in hub.events if n == EVENT_MODELS_DOWNLOAD_COMPLETED)
    assert completed["ok"] is True
    assert completed["files"][0]["sha256_verified"] is True


async def test_dispatcher_emits_failed_on_integrity_error(tmp_path: Path) -> None:
    hub = _CapturingHub()
    gateway = ModelsDownloadCommandGateway(
        hub=hub,
        models_dir=tmp_path / "models",
        manifest_path=_manifest(tmp_path, "f" * 64),  # wrong pin => integrity error
        fetch=_fetch_ok,
        specs=(_SPEC,),
    )

    async def send(env: Envelope) -> None:
        pass

    command = Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="models.download", id=str(uuid.uuid4()), payload={}
    )
    await dispatch_models_command(command, gateway, send)
    assert gateway._task is not None
    await gateway._task  # finish (integrity error is handled inside, not raised)
    names = [name for name, _ in hub.events]
    assert EVENT_MODELS_DOWNLOAD_FAILED in names
    failed = next(p for n, p in hub.events if n == EVENT_MODELS_DOWNLOAD_FAILED)
    assert failed["file"] == "tiny.bin"
    completed = next(p for n, p in hub.events if n == EVENT_MODELS_DOWNLOAD_COMPLETED)
    assert completed["ok"] is False


async def test_second_download_while_running_is_not_started(tmp_path: Path) -> None:
    import threading

    hub = _CapturingHub()
    # threading.Event: set/checked from the worker THREAD (asyncio.Event is
    # not thread-safe across the to_thread boundary).
    started = threading.Event()
    release = threading.Event()

    def _slow_fetch(url: str, dest: Path, progress) -> None:  # type: ignore[no-untyped-def]
        dest.write_bytes(_BYTES)
        started.set()
        release.wait(timeout=5.0)  # block until the test lets go (in-flight)

    gateway = ModelsDownloadCommandGateway(
        hub=hub,
        models_dir=tmp_path / "models",
        manifest_path=_manifest(tmp_path, _SHA),
        fetch=_slow_fetch,
        specs=(_SPEC,),
    )
    replies: list[Envelope] = []

    async def send(env: Envelope) -> None:
        replies.append(env)

    def _cmd() -> Envelope:
        return Envelope(
            v=1, kind=EnvelopeKind.COMMAND, name="models.download", id=str(uuid.uuid4()), payload={}
        )

    await dispatch_models_command(_cmd(), gateway, send)
    while not started.is_set():  # let the background task reach the thread
        await asyncio.sleep(0.01)
    await dispatch_models_command(_cmd(), gateway, send)  # while the first runs
    assert replies[0].payload["started"] is True
    assert replies[1].payload["started"] is False  # single-flight guard
    release.set()
    await gateway.shutdown()
