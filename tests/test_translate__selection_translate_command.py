"""selection.translate command dispatcher — Settings lang + summary prefer."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.protocol import PROTOCOL_VERSION, Envelope, EnvelopeKind
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    ProviderCompletionClient,
    CompletionRequest,
)
from engine.router.fallback_executor import ProviderRouter
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.storage.app_settings_repository import (
    SETTING_SELECTION_TRANSLATION_LANG,
    SETTING_SUMMARY_PROVIDER,
    write_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.translate.selection_translate_command_dispatcher import (
    SELECTION_TRANSLATE_COMMAND_NAME,
    SelectionTranslateGateway,
    dispatch_selection_translate_command,
)


class _OkClient(ProviderCompletionClient):
    def __init__(self, provider: Provider, text: str = "hola") -> None:
        self.provider = provider
        self._text = text
        self.calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> ProviderCompletion:
        self.calls.append(request)
        return ProviderCompletion(
            text=self._text,
            provider=self.provider,
            model=request.model,
            prompt_tokens=1,
            completion_tokens=1,
        )


class _Ledger:
    async def record(self, entry: RouterLedgerEntry) -> None:
        return None


@pytest.mark.asyncio
async def test_selection_translate_uses_settings_lang_and_prefers_ollama(
    tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        await write_setting(connection, SETTING_SELECTION_TRANSLATION_LANG, "Spanish")
        await write_setting(connection, SETTING_SUMMARY_PROVIDER, "ollama")
    finally:
        await connection.close()

    ollama = _OkClient(Provider.OLLAMA, "hola")
    gemini = _OkClient(Provider.GEMINI, "should-not-win")
    ledger = _Ledger()

    def factory(_recorder):  # noqa: ANN001
        return ProviderRouter(
            {Provider.OLLAMA: ollama, Provider.GEMINI: gemini}, ledger.record
        )

    gateway = SelectionTranslateGateway(tmp_db_path, real_migrations_dir, factory)
    replies: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        replies.append(envelope)

    command = Envelope(
        v=PROTOCOL_VERSION,
        kind=EnvelopeKind.COMMAND,
        name=SELECTION_TRANSLATE_COMMAND_NAME,
        id="sel-1",
        payload={"text": "hello"},
    )
    await dispatch_selection_translate_command(command, gateway, send)
    assert len(replies) == 1
    assert replies[0].name == "ok"
    assert replies[0].payload["translated"] == "hola"
    assert len(ollama.calls) == 1
    assert ollama.calls[0].task_type.value == "ask_synthesis"
    # User message must carry the Settings language when target_lang omitted.
    user_msg = ollama.calls[0].messages[0]
    assert isinstance(user_msg, ChatMessage)
    assert "Spanish" in user_msg.content
