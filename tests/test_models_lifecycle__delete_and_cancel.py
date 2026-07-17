"""Model-lifecycle wiring: cancel / delete / open_folder — dispatch + gateway.

Every test asserts fail-closed behaviour: path traversal is refused (the
delete never escapes the models directory), a bad payload never reaches the
gateway, an idle gateway reports "nothing to cancel" honestly, and the
dispatcher always replies (never silently drops a command).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from engine.protocol import Envelope, EnvelopeKind, EventBroadcastHub
from engine.wiring.models_download_command_dispatcher import (
    ModelsDownloadCommandGateway,
    dispatch_models_command,
)
from engine.wiring.models_lifecycle_ops import (
    cancel_in_flight_task,
    delete_model_file,
    open_folder_payload,
)

SendFn = Callable[[Envelope], Awaitable[None]]


def _collector() -> tuple[list[Envelope], SendFn]:
    sent: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        sent.append(envelope)

    return sent, send


def _cmd(name: str, payload: dict[str, object], cid: str = "c1") -> Envelope:
    return Envelope(v=1, kind=EnvelopeKind.COMMAND, name=name, id=cid, payload=payload)


# --------------------------------------------------------- pure ops helpers


def test_delete_model_file_removes_the_file(tmp_path: Path) -> None:
    (tmp_path / "ggml-tiny.bin").write_bytes(b"weights")
    result = delete_model_file(tmp_path, "ggml-tiny.bin")
    assert result == {"file": "ggml-tiny.bin", "deleted": True}
    assert not (tmp_path / "ggml-tiny.bin").exists()


def test_delete_model_file_refuses_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        delete_model_file(tmp_path, "does-not-exist.bin")


def test_delete_model_file_refuses_parent_traversal(tmp_path: Path) -> None:
    """Fail closed: even a filename that resolves outside models_dir (via a
    literal '..' segment surviving basename validation upstream) is refused
    at this layer too — defence in depth, not the only gate."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"do-not-delete")
    with pytest.raises(ValueError, match="outside the models directory"):
        delete_model_file(models_dir, "../secret.bin")
    assert secret.exists()  # never touched


def test_delete_model_file_refuses_a_nested_subdirectory_escape(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    nested = models_dir / "nested"
    nested.mkdir(parents=True)
    victim = nested / "inner.bin"
    victim.write_bytes(b"x")
    # A filename containing a separator would already be refused by the
    # payload validator; this proves the ops-layer gate holds on its own.
    with pytest.raises(ValueError, match="outside the models directory"):
        delete_model_file(models_dir, "nested/inner.bin")
    assert victim.exists()


def test_open_folder_payload_reports_the_configured_path(tmp_path: Path) -> None:
    assert open_folder_payload(tmp_path) == {"path": str(tmp_path)}


async def test_cancel_in_flight_task_returns_false_when_nothing_running() -> None:
    assert await cancel_in_flight_task(None) is False


async def test_cancel_in_flight_task_returns_false_for_an_already_done_task() -> None:
    async def _noop() -> None:
        return None

    task = asyncio.create_task(_noop())
    await task
    assert await cancel_in_flight_task(task) is False


async def test_cancel_in_flight_task_really_cancels_a_running_task() -> None:
    async def _sleep_forever() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(_sleep_forever())
    await asyncio.sleep(0)  # let it start
    assert await cancel_in_flight_task(task) is True
    assert task.cancelled()


# ---------------------------------------------------------- gateway + dispatch


def test_gateway_delete_model_file_uses_configured_models_dir(tmp_path: Path) -> None:
    (tmp_path / "ggml-base.bin").write_bytes(b"weights")
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    result = gateway.delete_model_file("ggml-base.bin")
    assert result == {"file": "ggml-base.bin", "deleted": True}


def test_gateway_open_folder_reports_the_configured_models_dir(tmp_path: Path) -> None:
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    assert gateway.open_folder() == {"path": str(tmp_path)}


async def test_gateway_cancel_download_is_false_when_idle(tmp_path: Path) -> None:
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    assert await gateway.cancel_download() is False


async def test_dispatch_cancel_replies_ok_with_cancelled_false_when_idle(
    tmp_path: Path,
) -> None:
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    sent, send = _collector()
    await dispatch_models_command(_cmd("models.cancel", {}), gateway, send)
    assert sent[0].name == "ok"
    assert sent[0].payload == {"cancelled": False}


async def test_dispatch_cancel_rejects_extra_fields(tmp_path: Path) -> None:
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    sent, send = _collector()
    await dispatch_models_command(_cmd("models.cancel", {"force": True}), gateway, send)
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "invalid_payload"


async def test_dispatch_delete_removes_the_file_and_replies_ok(tmp_path: Path) -> None:
    (tmp_path / "ggml-small.bin").write_bytes(b"weights")
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    sent, send = _collector()
    await dispatch_models_command(
        _cmd("models.delete", {"file": "ggml-small.bin"}), gateway, send
    )
    assert sent[0].name == "ok"
    assert sent[0].payload == {"file": "ggml-small.bin", "deleted": True}
    assert not (tmp_path / "ggml-small.bin").exists()


async def test_dispatch_delete_rejects_a_path_with_separators(tmp_path: Path) -> None:
    """The client can never smuggle a path — extra_forbid + basename-only
    validation refuses it before the gateway is even called."""
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    sent, send = _collector()
    await dispatch_models_command(
        _cmd("models.delete", {"file": "../../etc/passwd"}), gateway, send
    )
    assert sent[0].name == "error"
    assert sent[0].payload["code"] == "invalid_payload"


async def test_dispatch_delete_reports_missing_file_as_invalid_payload(tmp_path: Path) -> None:
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    sent, send = _collector()
    await dispatch_models_command(
        _cmd("models.delete", {"file": "nonexistent.bin"}), gateway, send
    )
    assert sent[0].name == "error"
    assert "not found" in str(sent[0].payload["message"])


async def test_dispatch_open_folder_replies_with_the_path(tmp_path: Path) -> None:
    gateway = ModelsDownloadCommandGateway(EventBroadcastHub(), models_dir=tmp_path)
    sent, send = _collector()
    await dispatch_models_command(_cmd("models.open_folder", {}), gateway, send)
    assert sent[0].name == "ok"
    assert sent[0].payload == {"path": str(tmp_path)}


async def test_dispatch_lifecycle_commands_refuse_when_gateway_unwired() -> None:
    sent, send = _collector()
    for name in ("models.cancel", "models.delete", "models.open_folder"):
        payload: dict[str, object] = (
            {"file": "x.bin"} if name == "models.delete" else {}
        )
        await dispatch_models_command(_cmd(name, payload), None, send)
    assert all(e.name == "error" for e in sent)
    assert all(e.payload["code"] == "unknown_command" for e in sent)
