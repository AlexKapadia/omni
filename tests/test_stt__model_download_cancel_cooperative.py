"""Cooperative models.download cancel: threading.Event per block + single-flight.

Cancelling must stop the fetch loop (not only the asyncio task) and keep
is_downloading True until the worker thread exits so a second download cannot
race on the same .partial file.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from engine.protocol import EventBroadcastHub
from engine.stt.model_weights_downloader import (
    ModelDownloadCancelled,
    ModelSpec,
    download_models_with_progress,
)
from engine.wiring.models_download_command_dispatcher import ModelsDownloadCommandGateway

_SPEC = ModelSpec(
    filename="slow.bin",
    url="https://example.test/slow.bin",
    description="slow synthetic",
)


def _slow_cancellable_fetch(
    url: str,
    destination: Path,
    progress: Callable[[int, int | None], None],
    cancel_event: threading.Event | None = None,
) -> None:
    """Fake fetch that writes in small blocks and honours cancel_event."""
    total = 1024 * 256 * 8  # 8 blocks
    done = 0
    with destination.open("wb") as out:
        while done < total:
            if cancel_event is not None and cancel_event.is_set():
                raise ModelDownloadCancelled("models.download cancelled")
            out.write(b"x" * (1024 * 256))
            done += 1024 * 256
            progress(done, total)
            time.sleep(0.05)  # give cancel a window between blocks


def test_download_models_with_progress_raises_on_cancel_event(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    raised = False
    try:
        download_models_with_progress(
            lambda *_: None,
            models_dir=tmp_path / "models",
            specs=(_SPEC,),
            fetch=_slow_cancellable_fetch,
            cancel_event=cancel,
        )
    except ModelDownloadCancelled:
        raised = True
    assert raised


async def test_cancel_holds_single_flight_until_worker_exits(tmp_path: Path) -> None:
    hub = EventBroadcastHub()
    gateway = ModelsDownloadCommandGateway(
        hub,
        models_dir=tmp_path / "models",
        fetch=_slow_cancellable_fetch,
        specs=(_SPEC,),
    )
    assert gateway.begin_download() is True
    assert gateway.is_downloading() is True
    # A second begin while the first is in flight must refuse.
    assert gateway.begin_download() is False

    cancelled = await gateway.cancel_download()
    assert cancelled is True
    # After cancel returns, the worker has exited — single-flight released.
    assert gateway.is_downloading() is False
    # A fresh download may start again.
    assert gateway.begin_download() is True
    await gateway.cancel_download()
