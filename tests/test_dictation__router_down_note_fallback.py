"""Router-down behaviour: fail OPEN for the user's words, CLOSED for actions.

Every provider failing (or the kill switch engaging) mid-dictation must
never lose what the user said: a note is still saved under a timestamp
title, and a command is still RECORDED (as unknown) — but nothing ever
becomes actionable without a real parsed intent.
"""

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_finalization import DictationReleaseFinalizer
from engine.dictation.dictation_intent_schema import DictationIntentType
from engine.dictation.dictation_intents_repository import list_dictation_intents
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.dictation.personal_dictionary import PersonalDictionary
from engine.router.completion_contract import ChatMessage, RoutedCompletion
from engine.router.router_errors import KillSwitchEngagedError, RouterUnavailableError
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

FIXED_NOW = datetime(2026, 7, 6, 9, 5, tzinfo=UTC)


class DownRouter:
    """Every call fails the way a fully-exhausted chain fails."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def __call__(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        self.calls += 1
        raise self._error


def _finalizer(
    tmp_db_path: Path, real_migrations_dir: Path, vault: Path, route: DownRouter
) -> DictationReleaseFinalizer:
    async def connection_factory() -> aiosqlite.Connection:
        await apply_migrations(tmp_db_path, real_migrations_dir)
        return await open_sqlite_connection(tmp_db_path)

    return DictationReleaseFinalizer(
        route=route,
        intents_connection_factory=connection_factory,
        vault_root_provider=lambda: vault,
        indexer=None,
        now=lambda: FIXED_NOW,
        # Hermetic: never read the real %LOCALAPPDATA% dictionary in tests.
        dictionary=PersonalDictionary(path=vault / "no-dictionary.txt"),
    )


async def test_note_is_saved_with_timestamp_title_when_router_unavailable(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = DownRouter(RouterUnavailableError("live_extraction", ()))
    finalizer = _finalizer(tmp_db_path, real_migrations_dir, vault, route)

    verbatim = "remember to buy milk"
    result = await finalizer.finalize(verbatim)

    assert result.mode is DictationMode.NOTE
    assert result.title_source == "fallback"
    assert result.note_title == "Dictation 2026-07-06 09.05"
    note_path = Path(result.note_path or "")
    assert note_path.is_file()
    assert verbatim in note_path.read_text(encoding="utf-8")  # words never lost
    assert result.provider is None and result.model is None  # honest provenance
    # Cleanup fell back too: the RAW text is the body — never blocked on cloud.
    assert result.cleanup_source == "raw_fallback"
    assert result.cleaned_text == verbatim
    # The daily line still lands — local features never depend on the cloud.
    daily = (vault / "Daily" / "2026-07-06.md").read_text(encoding="utf-8")
    assert note_path.stem in daily


async def test_note_is_saved_when_kill_switch_is_engaged(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """Kill switch halts egress; capture/vault must keep working (§5.6)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    route = DownRouter(KillSwitchEngagedError())
    finalizer = _finalizer(tmp_db_path, real_migrations_dir, vault, route)

    result = await finalizer.finalize("offline thought")

    assert result.note_path is not None and Path(result.note_path).is_file()
    assert result.title_source == "fallback"


async def test_command_with_router_down_is_recorded_unknown_never_lost(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = DownRouter(RouterUnavailableError("intent_parsing", ()))
    finalizer = _finalizer(tmp_db_path, real_migrations_dir, vault, route)

    verbatim = "Omni, schedule lunch with Tom on Friday"
    result = await finalizer.finalize(verbatim)

    assert result.mode is DictationMode.COMMAND
    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.UNKNOWN
    assert "router unavailable" in result.intent.parse_error
    # Recorded (words never lost), provider honestly NULL, vault untouched.
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        records = await list_dictation_intents(connection)
    finally:
        await connection.close()
    assert len(records) == 1
    assert records[0].raw_text == verbatim
    assert records[0].intent_type == "unknown"
    assert records[0].provider is None
    assert list(vault.iterdir()) == []  # closed for actions: no side effects


async def test_router_is_tried_exactly_once_per_release(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    """Retry policy lives INSIDE the router; the finalizer must not stack
    its own retries on top (that would double every latency budget)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    route = DownRouter(RouterUnavailableError("intent_parsing", ()))
    finalizer = _finalizer(tmp_db_path, real_migrations_dir, vault, route)
    await finalizer.finalize("Omni, do a thing")
    assert route.calls == 1
