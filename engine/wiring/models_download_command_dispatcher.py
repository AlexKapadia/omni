"""``models.download`` gateway + WS dispatch: real weights, real progress.

Purpose: the server-layer surface the onboarding wizard drives to fetch the
on-device STT models, rendering REAL progress bars. The command is
accepted immediately and the download runs in the background, streaming
``models.download.progress`` / ``.failed`` / ``.completed`` events over the
hub. Present files are re-verified (hashed) rather than re-fetched, so the
same command is also the retry AND the integrity check.
Pipeline position: driven by the connection handler for ``models.download``;
runs ``engine.stt.model_weights_downloader`` off the event loop.

Security invariants:
- Download SOURCES are the pinned first-party HTTPS URLs in the downloader
  — the client can never supply a URL (the payload takes no arguments).
- ``sha256_verified`` is honest: True only when the file's hash matches the
  pinned manifest; a mismatch deletes the file and reports a failure (fail
  closed — a corrupt model never loads).
- One download at a time: a second command while one is in flight is
  refused, never allowed to race on the same files.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_MODELS_DOWNLOAD,
    EVENT_MODELS_DOWNLOAD_COMPLETED,
    EVENT_MODELS_DOWNLOAD_FAILED,
    EVENT_MODELS_DOWNLOAD_PROGRESS,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    ModelsDownloadCommandPayload,
    ProtocolErrorCode,
    build_models_download_completed_payload,
    build_models_download_failed_payload,
    build_models_download_progress_payload,
    error_reply,
)
from engine.stt.model_weights_downloader import (
    FetchFn,
    ModelIntegrityError,
    ModelSpec,
    _https_fetch,
    download_models_with_progress,
)

logger = logging.getLogger(__name__)

MODELS_COMMAND_NAMES = frozenset({COMMAND_MODELS_DOWNLOAD})

SendFn = Callable[[Envelope], Awaitable[None]]


def _ok_reply(reply_id: str, payload: dict[str, object]) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION, kind=EnvelopeKind.REPLY, name="ok", id=reply_id, payload=payload
    )


class ModelsDownloadCommandGateway:
    """One per engine process; construction is inert (no network until asked)."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        models_dir: Path | None = None,
        manifest_path: Path | None = None,
        fetch: FetchFn = _https_fetch,
        specs: tuple[ModelSpec, ...] | None = None,
    ) -> None:
        self._hub = hub
        self._models_dir = models_dir
        self._manifest_path = manifest_path
        self._fetch = fetch
        self._specs = specs
        self._task: asyncio.Task[None] | None = None

    def is_downloading(self) -> bool:
        """True while a download task is in flight (single-flight guard)."""
        return self._task is not None and not self._task.done()

    def begin_download(self) -> bool:
        """Start the background download. Returns False if one is already running."""
        if self.is_downloading():
            return False
        self._task = asyncio.create_task(self._run_download())
        return True

    async def _run_download(self) -> None:
        """Run the blocking download off-loop, streaming events as it goes."""
        loop = asyncio.get_running_loop()

        def on_progress(
            file: str, received: int, total: int | None, verified: bool | None
        ) -> None:
            # Called from the worker THREAD: hop back onto the loop to emit.
            payload = build_models_download_progress_payload(file, received, total, verified)
            asyncio.run_coroutine_threadsafe(
                self._hub.broadcast_event(EVENT_MODELS_DOWNLOAD_PROGRESS, payload), loop
            )

        kwargs: dict[str, object] = {
            "models_dir": self._models_dir,
            "manifest_path": self._manifest_path,
            "fetch": self._fetch,
        }
        if self._specs is not None:
            kwargs["specs"] = self._specs
        try:
            files = await asyncio.to_thread(
                download_models_with_progress, on_progress, **kwargs
            )
        except ModelIntegrityError as exc:
            # Honest per-file failure; the corrupt file was already deleted.
            await self._hub.broadcast_event(
                EVENT_MODELS_DOWNLOAD_FAILED,
                build_models_download_failed_payload(exc.filename, str(exc)),
            )
            await self._hub.broadcast_event(
                EVENT_MODELS_DOWNLOAD_COMPLETED,
                build_models_download_completed_payload(ok=False, files=[]),
            )
            return
        except Exception as exc:
            logger.exception("models.download failed")
            await self._hub.broadcast_event(
                EVENT_MODELS_DOWNLOAD_FAILED,
                # No filename is known for a non-integrity failure (network, disk).
                build_models_download_failed_payload("", f"download failed: {exc}"),
            )
            await self._hub.broadcast_event(
                EVENT_MODELS_DOWNLOAD_COMPLETED,
                build_models_download_completed_payload(ok=False, files=[]),
            )
            return
        await self._hub.broadcast_event(
            EVENT_MODELS_DOWNLOAD_COMPLETED,
            build_models_download_completed_payload(ok=True, files=files),
        )

    async def shutdown(self) -> None:
        """Cancel any in-flight download so it never outlives the process."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            # Await the cancellation so no worker outlives the process; a
            # download error during teardown is irrelevant (we are stopping).
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task


async def dispatch_models_command(
    command: Envelope, gateway: ModelsDownloadCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated models.download command, always replying (fail closed)."""
    if gateway is None:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.UNKNOWN_COMMAND,
                "model download is not available",
            )
        )
        return
    try:
        ModelsDownloadCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "models.download payload failed validation",
            )
        )
        return
    started = gateway.begin_download()
    # Accepted-immediately: progress/failed/completed arrive as events. A
    # second request while one is running is reported honestly, not raced.
    await send(_ok_reply(command.id, {"started": started}))
