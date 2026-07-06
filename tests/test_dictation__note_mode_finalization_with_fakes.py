"""Release finalization, NOTE mode: verbatim note -> vault + index + daily.

The REAL finalizer runs against a real migrated SQLite file and a real
tmp_path vault, with only the router and indexer faked (support in
``tests/dictation_finalization_test_support.py``). Asserts the binding
invariant end to end: the note body / persisted raw transcript is VERBATIM,
degradations (malformed titles, indexer outages, silence) are honest, and
note mode never touches the intents database.
"""

import json
from pathlib import Path

import aiosqlite

from engine.dictation.dictation_finalization import DictationReleaseFinalizer
from engine.dictation.dictation_mode_splitter import DictationMode
from engine.dictation.personal_dictionary import PersonalDictionary
from tests.dictation_finalization_test_support import (
    FIXED_NOW,
    FakeIndexer,
    FakeRoute,
    make_finalizer,
    read_intents,
)


async def test_note_flow_writes_verbatim_note_indexes_and_logs_daily_line(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    cleaned = "Remember to buy milk and maybe eggs."
    route = FakeRoute(
        {
            "live_extraction": json.dumps({"title": "Buy milk"}),
            "dictation_cleanup": json.dumps({"cleaned": cleaned}),
        }
    )
    indexer = FakeIndexer()
    finalizer = make_finalizer(tmp_db_path, real_migrations_dir, vault, route, indexer)

    verbatim = "remember to buy milk and, um, maybe eggs"
    result = await finalizer.finalize(verbatim)

    assert result.mode is DictationMode.NOTE
    assert result.text == verbatim
    assert result.note_title == "Buy milk"
    assert result.title_source == "model"
    assert result.degraded_reason is None
    assert result.cleaned_text == cleaned
    assert result.cleanup_source == "model"
    # The note landed in Inbox: CLEANED body + RAW retained byte-identical
    # (fidelity mandate: raw is ground truth, cleanup is a separate artifact).
    note_path = Path(result.note_path or "")
    assert note_path.parent == vault / "Inbox"
    content = note_path.read_text(encoding="utf-8")
    assert cleaned in content  # cleaned body
    assert verbatim in content  # raw retained, exact and unrewritten
    assert "Raw transcript" in content  # collapsed raw section present
    assert "source: dictation" in content  # honest provenance
    # Indexed incrementally.
    assert indexer.indexed == [note_path]
    # Daily-note line references the note.
    daily = (vault / "Daily" / "2026-07-06.md").read_text(encoding="utf-8")
    assert f"- 14:30 dictated [[{note_path.stem}]]" in daily
    # And nothing was recorded as a command.
    assert await read_intents(tmp_db_path) == []


async def test_note_flow_with_malformed_title_falls_back_but_saves(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({"live_extraction": "not json", "dictation_cleanup": "not json"})
    finalizer = make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("thoughts about the offsite")

    assert result.title_source == "fallback"
    assert result.note_title == "Dictation 2026-07-06 14.30"
    assert result.note_path is not None and Path(result.note_path).is_file()
    # Malformed cleanup output -> raw fallback: the words land untouched.
    assert result.cleanup_source == "raw_fallback"
    assert result.cleaned_text == "thoughts about the offsite"
    # Index not wired -> honest degradation note, but the note IS saved.
    assert result.degraded_reason is not None
    assert "not yet searchable" in result.degraded_reason
    assert "cleanup output malformed" in result.degraded_reason


async def _unused_connection_factory() -> aiosqlite.Connection:
    raise AssertionError("note mode must never open the intents database")


async def test_note_flow_indexer_failure_degrades_honestly_note_kept(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    class ExplodingIndexer:
        async def index_changed_files(self, changed_paths: object) -> object:
            raise RuntimeError("sqlite-vec missing")

    route = FakeRoute(
        {
            "live_extraction": json.dumps({"title": "Offsite"}),
            "dictation_cleanup": json.dumps({"cleaned": "Offsite planning ideas."}),
        }
    )
    finalizer = DictationReleaseFinalizer(
        route=route,
        intents_connection_factory=_unused_connection_factory,
        vault_root_provider=lambda: vault,
        indexer=ExplodingIndexer(),
        now=lambda: FIXED_NOW,
        dictionary=PersonalDictionary(path=vault / "no-dictionary.txt"),
    )
    result = await finalizer.finalize("offsite planning ideas")
    assert result.note_path is not None and Path(result.note_path).is_file()
    assert result.degraded_reason is not None
    assert "indexing failed" in result.degraded_reason


async def test_release_before_speech_saves_nothing_and_says_so(
    tmp_db_path: Path, real_migrations_dir: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    route = FakeRoute({})
    finalizer = make_finalizer(tmp_db_path, real_migrations_dir, vault, route, None)

    result = await finalizer.finalize("   ")

    assert result.note_path is None
    assert result.intent is None
    assert result.degraded_reason == "no speech captured before release"
    assert route.calls == []  # no cloud call for silence
    assert list((vault).iterdir()) == []  # nothing written anywhere
