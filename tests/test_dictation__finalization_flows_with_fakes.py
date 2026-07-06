"""Release finalization flows: note -> vault+index+daily, command -> record.

The REAL finalizer runs against a real migrated SQLite file and a real
tmp_path vault, with only the router and indexer faked. Asserts the two
binding invariants end to end: the note body / persisted raw_text is the
VERBATIM transcript, and command mode only ever RECORDS (no execution
path exists — the strongest proof is that nothing but the intents table
and the vault is touched).
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_finalization import (
    DictationFinalResult,
    DictationReleaseFinalizer,
)
from engine.dictation.dictation_intent_schema import DictationIntentType
from engine.dictation.dictation_intents_repository import list_dictation_intents
from engine.dictation.dictation_mode_splitter import DictationMode
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


def _make_finalizer(
    tmp_db_path: Path,
    real_migrations_dir: Path,
    vault_root: Path,
    route: FakeRoute,
    indexer: FakeIndexer | None,
) -> DictationReleaseFinalizer:
    async def connection_factory() -> aiosqlite.Connection:
        await apply_migrations(tmp_db_path, real_migrations_dir)
        return await open_sqlite_connection(tmp_db_path)

    return DictationReleaseFinalizer(
        route=route,
        intents_connection_factory=connection_factory,
        vault_root_provider=lambda: vault_root,
        indexer=indexer,
        now=lambda: FIXED_NOW,
    )


async def _read_intents(tmp_db_path: Path) -> list[object]:
    # Note-mode runs never open the intents DB, so the schema may not exist
    # yet when the test comes to verify emptiness — apply it here.
    await apply_migrations(tmp_db_path, Path(__file__).resolve().parent.parent / "migrations")
    connection = await open_sqlite_connection(tmp_db_path)
    try:
        return list(await list_dictation_intents(connection))
    finally:
        await connection.close()


# ---------------------------------------------------------------------------
# NOTE mode
# ---------------------------------------------------------------------------
async def test_note_flow_writes_verbatim_note_indexes_and_logs_daily_line(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({"live_extraction": json.dumps({"title": "Buy milk"})})
    indexer = FakeIndexer()
    finalizer = _make_finalizer(tmp_db_path, real_migrations_dir, vault, route, indexer)

    verbatim = "remember to buy milk and, um, maybe eggs"
    result = await finalizer.finalize(verbatim)

    assert result.mode is DictationMode.NOTE
    assert result.text == verbatim
    assert result.note_title == "Buy milk"
    assert result.title_source == "model"
    assert result.degraded_reason is None
    # The note landed in Inbox with the VERBATIM body (fidelity mandate).
    note_path = Path(result.note_path or "")
    assert note_path.parent == vault / "Inbox"
    content = note_path.read_text(encoding="utf-8")
    assert verbatim in content  # exact, unrewritten
    assert "source: dictation" in content  # honest provenance
    # Indexed incrementally.
    assert indexer.indexed == [note_path]
    # Daily-note line references the note.
    daily = (vault / "Daily" / "2026-07-06.md").read_text(encoding="utf-8")
    assert f"- 14:30 dictated [[{note_path.stem}]]" in daily
    # And nothing was recorded as a command.
    assert await _read_intents(tmp_db_path) == []


async def test_note_flow_with_malformed_title_falls_back_but_saves(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({"live_extraction": "not json"})
    finalizer = _make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("thoughts about the offsite")

    assert result.title_source == "fallback"
    assert result.note_title == "Dictation 2026-07-06 14.30"
    assert result.note_path is not None and Path(result.note_path).is_file()
    # Index not wired -> honest degradation note, but the note IS saved.
    assert result.degraded_reason is not None
    assert "not yet searchable" in result.degraded_reason


async def test_note_flow_indexer_failure_degrades_honestly_note_kept(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    class ExplodingIndexer:
        async def index_changed_files(self, changed_paths: object) -> object:
            raise RuntimeError("sqlite-vec missing")

    route = FakeRoute({"live_extraction": json.dumps({"title": "Offsite"})})
    finalizer = DictationReleaseFinalizer(
        route=route,
        intents_connection_factory=_unused_connection_factory,
        vault_root_provider=lambda: vault,
        indexer=ExplodingIndexer(),
        now=lambda: FIXED_NOW,
    )
    result = await finalizer.finalize("offsite planning ideas")
    assert result.note_path is not None and Path(result.note_path).is_file()
    assert result.degraded_reason is not None
    assert "indexing failed" in result.degraded_reason


async def _unused_connection_factory() -> aiosqlite.Connection:
    raise AssertionError("note mode must never open the intents database")


async def test_release_before_speech_saves_nothing_and_says_so(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({})
    finalizer = _make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("   ")

    assert result.note_path is None
    assert result.intent is None
    assert result.degraded_reason == "no speech captured before release"
    assert route.calls == []  # no cloud call for silence
    assert list((vault).iterdir()) == []  # nothing written anywhere


# ---------------------------------------------------------------------------
# COMMAND mode
# ---------------------------------------------------------------------------
async def test_command_flow_records_intent_and_never_touches_the_vault(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    intent_json = json.dumps(
        {
            "intent_type": "create_event",
            "fields": {"title": "lunch with Tom", "date": "Friday", "time": "13:00"},
            "confidence": 0.92,
        }
    )
    route = FakeRoute({"intent_parsing": intent_json})
    finalizer = _make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    verbatim = "Omni, schedule lunch with Tom on Friday at one"
    result = await finalizer.finalize(verbatim)

    assert result.mode is DictationMode.COMMAND
    assert result.text == verbatim
    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.CREATE_EVENT
    assert result.intent.confidence == 0.92
    assert result.note_path is None  # commands never write notes
    # The router saw ONLY the command body (wake word stripped), as data.
    assert route.calls == [("intent_parsing", "schedule lunch with Tom on Friday at one")]
    # Persisted append-only with the FULL verbatim text.
    records = await _read_intents(tmp_db_path)
    assert len(records) == 1
    record = records[0]
    assert record.raw_text == verbatim  # type: ignore[attr-defined]
    assert record.intent_type == "create_event"  # type: ignore[attr-defined]
    # The vault stayed untouched — recording is the WHOLE write path.
    assert list(vault.iterdir()) == []


async def test_command_with_garbage_model_output_records_unknown(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({"intent_parsing": "I cannot help with that."})
    finalizer = _make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("Omni, do something ineffable")

    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.UNKNOWN
    records = await _read_intents(tmp_db_path)
    assert records[0].intent_type == "unknown"  # type: ignore[attr-defined]
    assert list(vault.iterdir()) == []


async def test_wake_word_alone_records_unknown_without_routing(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({})
    finalizer = _make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("Omni")

    assert result.mode is DictationMode.COMMAND
    assert result.intent is not None
    assert result.intent.intent_type is DictationIntentType.UNKNOWN
    assert result.intent.parse_error == "empty command after wake word"
    assert route.calls == []  # nothing to parse -> no cloud call
    records = await _read_intents(tmp_db_path)
    assert records[0].raw_text == "Omni"  # type: ignore[attr-defined]


def test_final_result_is_immutable() -> None:
    """The result feeds dictation.final — a mutable result could drift
    between what happened and what is reported."""
    result = DictationFinalResult(mode=DictationMode.NOTE, text="x")
    try:
        result.text = "y"  # type: ignore[misc]
        raise AssertionError("DictationFinalResult must be frozen")
    except AttributeError:
        pass
