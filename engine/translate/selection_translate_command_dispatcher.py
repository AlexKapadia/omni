"""``selection.translate`` dispatch — Settings + WS path for selection translation.

Purpose: validates untrusted selected text, reads
``selection_translation_lang`` / summary Settings when needed, runs
``translate_selection`` through the keyed router, replies with
``{ translated }`` or a typed error.
Pipeline position: owned by the ask command surface (same gateway lifecycle);
called from ``dispatch_ask_command`` when the name is ``selection.translate``.

Security: text is untrusted DATA only; kill-switch / router refusals fail honest.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import ValidationError

from engine.protocol import PROTOCOL_VERSION, Envelope, EnvelopeKind, ProtocolErrorCode, error_reply
from engine.protocol.selection_translate_payloads import SelectionTranslateCommandPayload
from engine.router import (
    ProviderRouter,
    RouterError,
    RouterLedgerEntry,
    build_provider_clients,
    insert_router_ledger_entry,
)
from engine.security import ProviderKeyStore
from engine.storage.app_settings_repository import (
    SETTING_SELECTION_TRANSLATION_LANG,
    SETTING_SUMMARY_MODEL_ID,
    SETTING_SUMMARY_PROVIDER,
    read_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.translate.selection_translate_service import translate_selection

logger = logging.getLogger(__name__)

SELECTION_TRANSLATE_COMMAND_NAME = "selection.translate"
SELECTION_TRANSLATE_REPLY_NAME = "ok"
SELECTION_TRANSLATE_ERROR_CODE = "selection_translate_error"

SendFn = Callable[[Envelope], Awaitable[None]]
LedgerRecorder = Callable[[RouterLedgerEntry], Awaitable[None]]
TranslateRouterFactory = Callable[[LedgerRecorder], ProviderRouter]


def _default_router_factory(recorder: LedgerRecorder) -> ProviderRouter:
    return ProviderRouter(build_provider_clients(ProviderKeyStore()), recorder)


class SelectionTranslateGateway:
    """One per engine process; construction is inert (no keys, no I/O)."""

    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        router_factory: TranslateRouterFactory | None = None,
    ) -> None:
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self._router_factory = router_factory if router_factory else _default_router_factory

    async def translate(self, text: str, target_lang: str | None) -> str:
        await apply_migrations(self.db_path, self.migrations_dir)
        connection = await open_sqlite_connection(self.db_path)
        try:

            async def record(entry: RouterLedgerEntry) -> None:
                await insert_router_ledger_entry(connection, entry)

            router = self._router_factory(record)
            lang_raw = target_lang
            if lang_raw is None or not str(lang_raw).strip():
                stored = await read_setting(connection, SETTING_SELECTION_TRANSLATION_LANG)
                lang_raw = stored if isinstance(stored, str) else "English"
            summary_model_raw = await read_setting(connection, SETTING_SUMMARY_MODEL_ID)
            preferred_model = summary_model_raw if isinstance(summary_model_raw, str) else None
            summary_provider_raw = await read_setting(connection, SETTING_SUMMARY_PROVIDER)
            preferred_provider = (
                summary_provider_raw if isinstance(summary_provider_raw, str) else None
            )
            return await translate_selection(
                router.route,
                text,
                str(lang_raw),
                preferred_model=preferred_model,
                preferred_provider=preferred_provider,
            )
        finally:
            await connection.close()


async def dispatch_selection_translate_command(
    command: Envelope,
    gateway: SelectionTranslateGateway | None,
    send: SendFn,
) -> None:
    try:
        payload = SelectionTranslateCommandPayload.model_validate(command.payload)
    except ValidationError:
        await send(
            error_reply(
                command.id,
                ProtocolErrorCode.INVALID_PAYLOAD,
                "selection.translate payload failed validation",
            )
        )
        return
    if gateway is None:
        await send(_error_reply(command.id, "selection translate is not available"))
        return
    try:
        translated = await gateway.translate(payload.text, payload.target_lang)
    except RouterError as exc:
        await send(_error_reply(command.id, str(exc)))
        return
    except ValueError as exc:
        await send(_error_reply(command.id, str(exc)))
        return
    except Exception as exc:
        logger.exception("selection.translate failed")
        await send(_error_reply(command.id, f"selection translate failed: {exc}"))
        return
    await send(
        Envelope(
            v=PROTOCOL_VERSION,
            kind=EnvelopeKind.REPLY,
            name=SELECTION_TRANSLATE_REPLY_NAME,
            id=command.id,
            payload={"translated": translated},
        )
    )


def _error_reply(reply_id: str, message: str) -> Envelope:
    return Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.REPLY,
        name="error",
        id=reply_id,
        payload={"code": SELECTION_TRANSLATE_ERROR_CODE, "message": message},
    )
