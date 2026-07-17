"""``models.download`` gateway + WS dispatch: real weights, real progress.

Purpose: the server-layer surface Settings/onboarding drive to fetch on-device
STT models, streaming REAL progress events. Payload is either the core
Silero+Parakeet bundle (default) or ``bundle=whisper`` + an allowlisted
``model_id``. Present files are re-verified rather than re-fetched.
Pipeline position: driven by the connection handler for ``models.download``.

Security invariants:
- Download SOURCES are pinned in the engine (HTTPS URLs / HF repo ids) —
  the client supplies only an allowlisted id, never a URL.
- ``sha256_verified`` is honest for core weights; Whisper HF trees report
  unverified (no Omni-pinned manifest hash yet).
- One download at a time: a second command while one is in flight is
  refused, never allowed to race on the same files.
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from engine.protocol import (
    COMMAND_MODELS_CANCEL,
    COMMAND_MODELS_DELETE,
    COMMAND_MODELS_DOWNLOAD,
    COMMAND_MODELS_OPEN_FOLDER,
    EVENT_MODELS_DOWNLOAD_COMPLETED,
    EVENT_MODELS_DOWNLOAD_FAILED,
    EVENT_MODELS_DOWNLOAD_PROGRESS,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    ModelsCancelCommandPayload,
    ModelsDeleteCommandPayload,
    ModelsDownloadCommandPayload,
    ModelsOpenFolderCommandPayload,
    ProtocolErrorCode,
    build_models_download_completed_payload,
    build_models_download_failed_payload,
    build_models_download_progress_payload,
    error_reply,
)
from engine.stt.model_weights_downloader import (
    FetchFn,
    ModelDownloadCancelled,
    ModelIntegrityError,
    ModelSpec,
    _https_fetch,
    download_models_with_progress,
    models_directory,
)
from engine.stt.whisper_model_catalog import download_whisper_model
from engine.wiring.models_lifecycle_ops import (
    delete_model_file as _delete_model_file_op,
)
from engine.wiring.models_lifecycle_ops import open_folder_payload

logger = logging.getLogger(__name__)

MODELS_COMMAND_NAMES = frozenset(
    {
        COMMAND_MODELS_DOWNLOAD,
        COMMAND_MODELS_CANCEL,
        COMMAND_MODELS_DELETE,
        COMMAND_MODELS_OPEN_FOLDER,
    }
)

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
        # Cooperative cancel for the worker thread (asyncio cancel alone cannot
        # stop a blocked urllib read). Single-flight stays held until the thread
        # exits so a second download cannot open the same .partial file.
        self._cancel_event = threading.Event()

    def is_downloading(self) -> bool:
        """True while a download task is in flight (single-flight guard)."""
        return self._task is not None and not self._task.done()

    def begin_download(self, *, bundle: str = "core", model_id: str | None = None) -> bool:
        """Start the background download. Returns False if one is already running."""
        if self.is_downloading():
            return False
        self._cancel_event = threading.Event()
        self._task = asyncio.create_task(self._run_download(bundle=bundle, model_id=model_id))
        return True

    async def _run_download(self, *, bundle: str, model_id: str | None) -> None:
        """Run the blocking download off-loop, streaming events as it goes."""
        loop = asyncio.get_running_loop()
        cancel_event = self._cancel_event

        def on_progress(
            file: str, received: int, total: int | None, verified: bool | None
        ) -> None:
            if cancel_event.is_set():
                return  # stop progress spam after cancel
            payload = build_models_download_progress_payload(file, received, total, verified)
            asyncio.run_coroutine_threadsafe(
                self._hub.broadcast_event(EVENT_MODELS_DOWNLOAD_PROGRESS, payload), loop
            )

        models_dir = self._models_dir if self._models_dir is not None else models_directory()
        specs = self._specs

        def _download() -> list[dict[str, Any]]:
            if bundle == "whisper":
                if model_id is None:
                    raise ValueError("model_id required for whisper bundle")
                entry = download_whisper_model(model_id, models_dir, on_progress)
                return [entry]
            if specs is not None:
                return download_models_with_progress(
                    on_progress,
                    models_dir=self._models_dir,
                    manifest_path=self._manifest_path,
                    fetch=self._fetch,
                    specs=specs,
                    cancel_event=cancel_event,
                )
            return download_models_with_progress(
                on_progress,
                models_dir=self._models_dir,
                manifest_path=self._manifest_path,
                fetch=self._fetch,
                cancel_event=cancel_event,
            )

        try:
            files = await asyncio.to_thread(_download)
        except ModelDownloadCancelled:
            await self._hub.broadcast_event(
                EVENT_MODELS_DOWNLOAD_FAILED,
                build_models_download_failed_payload("", "download cancelled"),
            )
            await self._hub.broadcast_event(
                EVENT_MODELS_DOWNLOAD_COMPLETED,
                build_models_download_completed_payload(ok=False, files=[]),
            )
            return
        except ModelIntegrityError as exc:
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
        await self.cancel_download()

    async def cancel_download(self) -> bool:
        """User-requested cancel. Sets the thread Event then awaits worker exit.

        Does NOT asyncio-cancel the task alone: that would leave the worker
        thread writing to .partial while is_downloading flips false. Single-
        flight remains held until to_thread returns (thread exited).
        """
        task = self._task
        if task is None or task.done():
            return False
        self._cancel_event.set()  # cooperative: checked per 256KB block
        with contextlib.suppress(Exception):
            await task  # drain until worker thread exits
        return True

    def delete_model_file(self, filename: str) -> dict[str, object]:
        """Delete one weight file, strictly confined to the models directory."""
        models_dir = self._models_dir if self._models_dir is not None else models_directory()
        return _delete_model_file_op(models_dir, filename)

    def open_folder(self) -> dict[str, object]:
        """The models directory path, for the UI to reveal in Explorer."""
        models_dir = self._models_dir if self._models_dir is not None else models_directory()
        return open_folder_payload(models_dir)


async def dispatch_models_command(
    command: Envelope, gateway: ModelsDownloadCommandGateway | None, send: SendFn
) -> None:
    """Handle one validated models.* command, always replying (fail closed)."""
    if gateway is None:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.UNKNOWN_COMMAND,
                "model download is not available",
            )
        )
        return
    name = command.name
    if name == COMMAND_MODELS_DOWNLOAD:
        await _dispatch_download(command, gateway, send)
    elif name == COMMAND_MODELS_CANCEL:
        await _dispatch_cancel(command, gateway, send)
    elif name == COMMAND_MODELS_DELETE:
        await _dispatch_delete(command, gateway, send)
    elif name == COMMAND_MODELS_OPEN_FOLDER:
        await _dispatch_open_folder(command, gateway, send)


async def _dispatch_download(
    command: Envelope, gateway: ModelsDownloadCommandGateway, send: SendFn
) -> None:
    try:
        payload = ModelsDownloadCommandPayload.model_validate(command.payload)
    except ValidationError as exc:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                f"models.download payload failed validation: {exc.errors()[0]['msg']}",
            )
        )
        return
    started = gateway.begin_download(bundle=payload.bundle, model_id=payload.model_id)
    await send(_ok_reply(command.id, {"started": started, "bundle": payload.bundle}))


async def _dispatch_cancel(
    command: Envelope, gateway: ModelsDownloadCommandGateway, send: SendFn
) -> None:
    try:
        ModelsCancelCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "models.cancel payload failed validation",
            )
        )
        return
    cancelled = await gateway.cancel_download()
    await send(_ok_reply(command.id, {"cancelled": cancelled}))


async def _dispatch_delete(
    command: Envelope, gateway: ModelsDownloadCommandGateway, send: SendFn
) -> None:
    try:
        payload = ModelsDeleteCommandPayload.model_validate(command.payload)
    except ValidationError as exc:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                f"models.delete payload failed validation: {exc.errors()[0]['msg']}",
            )
        )
        return
    try:
        result = gateway.delete_model_file(payload.file)
    except ValueError as exc:
        await send(
            error_reply(command.id, ProtocolErrorCode.INVALID_PAYLOAD, str(exc))
        )
        return
    await send(_ok_reply(command.id, result))


async def _dispatch_open_folder(
    command: Envelope, gateway: ModelsDownloadCommandGateway, send: SendFn
) -> None:
    try:
        ModelsOpenFolderCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "models.open_folder payload failed validation",
            )
        )
        return
    await send(_ok_reply(command.id, gateway.open_folder()))
