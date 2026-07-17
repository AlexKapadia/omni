"""Model-lifecycle operations: cancel / delete / open-folder for on-device weights.

Purpose: split out of ``models_download_command_dispatcher`` (which owns the
download flow) to keep that module under the 300-line file cap. These are
the individually-testable operations Settings drives to manage
already-downloaded (or in-flight) weight files.
Pipeline position: called by
``engine.wiring.models_download_command_dispatcher``.

Security invariant: ``delete_model_file`` refuses any resolved path that
escapes ``models_dir`` (path-traversal defence) — the payload-level bare-
filename check is defence in depth, not the only gate.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path


async def cancel_in_flight_task(task: asyncio.Task[None] | None) -> bool:
    """Cancel ``task`` if it is running; True iff a real cancellation happened."""
    if task is None or task.done():
        return False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
    return True


def delete_model_file(models_dir: Path, filename: str) -> dict[str, object]:
    """Delete one weight file, strictly confined to ``models_dir``.

    Fail closed on path traversal: the resolved target must be a direct
    child of the resolved models directory, never elsewhere on disk.
    """
    resolved_dir = models_dir.resolve()
    target = (resolved_dir / filename).resolve()
    if target.parent != resolved_dir:
        raise ValueError("refusing to delete a file outside the models directory")
    if not target.is_file():
        raise ValueError(f"model file not found: {filename}")
    target.unlink()
    return {"file": filename, "deleted": True}


def open_folder_payload(models_dir: Path) -> dict[str, object]:
    """The models directory path, for the UI to reveal in Explorer."""
    return {"path": str(models_dir)}
