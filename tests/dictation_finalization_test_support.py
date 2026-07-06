"""Shared fakes + builders for the dictation release-finalization suites.

``FakeRoute`` replays per-task canned completions and RECORDS every call so
tests can prove exactly what would have gone over the wire (wake word
stripped, command body only). ``FakeIndexer`` records indexed paths.
``make_finalizer`` assembles the REAL finalizer against a real migrated
SQLite file and a real tmp_path vault, hermetic from the box's personal
dictionary. No network anywhere (unit-test discipline).
"""

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_finalization import DictationReleaseFinalizer
from engine.dictation.dictation_intents_repository import list_dictation_intents
from engine.dictation.personal_dictionary import PersonalDictionary
from engine.router.completion_contract import (
    ChatMessage,
    Provider,
    ProviderCompletion,
    RoutedCompletion,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

FIXED_NOW = datetime(2026, 7, 6, 14, 30, tzinfo=UTC)


class FakeRoute:
    """Scripted router: returns per-task canned completions; logs calls."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str]] = []  # (task_type, data content)

    async def __call__(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        self.calls.append((task_type, messages[0].content))
        return RoutedCompletion(
            completion=ProviderCompletion(
                text=self._responses[task_type],
                provider=Provider.GROQ,
                model="llama-3.3-70b-versatile",
                prompt_tokens=10,
                completion_tokens=5,
            ),
            provider=Provider.GROQ,
            model="llama-3.3-70b-versatile",
            latency_ms=321,
        )


class FakeIndexer:
    def __init__(self) -> None:
        self.indexed: list[Path] = []

    async def index_changed_files(self, changed_paths: object) -> object:
        assert isinstance(changed_paths, list)
        self.indexed.extend(changed_paths)
        return None


def make_finalizer(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    vault_root: Path,
    route: FakeRoute,
    indexer: FakeIndexer | None,
) -> DictationReleaseFinalizer:
    """The REAL finalizer on real migrations; only router + indexer faked."""

    async def connection_factory() -> aiosqlite.Connection:
        await apply_migrations(tmp_db_path, real_migrations_dir)
        return await open_sqlite_connection(tmp_db_path)

    return DictationReleaseFinalizer(
        route=route,
        intents_connection_factory=connection_factory,
        vault_root_provider=lambda: vault_root,
        indexer=indexer,
        now=lambda: FIXED_NOW,
        # Hermetic: never read the real %LOCALAPPDATA% dictionary in tests.
        dictionary=PersonalDictionary(path=vault_root / "no-dictionary.txt"),
    )


async def read_intents(tmp_db_path: Path) -> list[object]:
    """Every persisted dictation intent — the append-only command record."""
    # Note-mode runs never open the intents DB, so the schema may not exist
    # yet when the test comes to verify emptiness — apply it here.
    await apply_migrations(tmp_db_path, Path(__file__).resolve().parent.parent / "migrations")
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        return list(await list_dictation_intents(connection))
    finally:
        await connection.close()
