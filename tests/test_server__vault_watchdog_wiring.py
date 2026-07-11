"""Vault watchdog wiring: watcher feed -> debounced reindex; honest OFF states.

Drives the REAL ``VaultWatchdogServerWiring`` with a FAKE watcher starter
(no OS observer, no watchdog thread) against a tmp_path SQLite database and
a tmp_path synthetic vault, pinning:
- changed files fed through the watcher callback are indexed after the
  debounce window (chunks + FTS really land, queryable);
- a burst of events becomes ONE indexing pass (debounce);
- deletions remove the note's index rows;
- OMNI_VAULT_DIR absent (vault_root=None) -> watcher OFF with one honest
  log line and the starter is NEVER called (fail closed);
- a missing watchdog dependency -> watcher OFF with an explicit error log,
  never a pretend-active watcher.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from engine.index.index_layer_errors import IndexDependencyMissingError
from engine.storage import apply_migrations, open_sqlite_connection
from engine.wiring.vault_watchdog_server_wiring import VaultWatchdogServerWiring
from tests.conftest import REPO_ROOT

MIGRATIONS = REPO_ROOT / "migrations"


class FakeObserver:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        pass


class FakeWatcherStarter:
    """Records the wiring's callback so tests feed change events directly."""

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.callback: Any = None
        self.observer = FakeObserver()
        self.observers: list[FakeObserver] = []

    def __call__(self, vault_root: Path, on_change: Any) -> FakeObserver:
        self.calls.append(vault_root)
        self.callback = on_change
        self.observer = FakeObserver()
        self.observers.append(self.observer)
        return self.observer


async def fts_hits(tmp_db: Path, needle: str) -> int:
    connection = await open_sqlite_connection(tmp_db)
    try:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (needle,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        return int(row[0])
    finally:
        await connection.close()


def make_wiring(
    tmp_db: Path, vault_root: Path | None, starter: FakeWatcherStarter
) -> VaultWatchdogServerWiring:
    return VaultWatchdogServerWiring(
        db_path=tmp_db,
        migrations_dir=MIGRATIONS,
        vault_root=vault_root,
        watcher_starter=starter,
        debounce_seconds=0.02,  # fast debounce keeps the suite quick
    )


async def wait_until(predicate: Any, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


async def test_watcher_feed_reindexes_after_debounce_and_fts_finds_the_text(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    await apply_migrations(tmp_db_path, MIGRATIONS)  # so the FTS poll can query
    note = tmp_path / "Projects" / "omni.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Omni\n\nzanzibar rollout plan\n", encoding="utf-8")
    starter = FakeWatcherStarter()
    wiring = make_wiring(tmp_db_path, tmp_path, starter)
    wiring.start()
    assert wiring.is_watching and starter.calls == [tmp_path]
    starter.callback([note])  # the watcher module's callback contract

    async def indexed() -> bool:
        return await fts_hits(tmp_db_path, "zanzibar") > 0

    await wait_until(indexed)
    # An external edit re-indexes the SAME note (hash change detected).
    note.write_text("# Omni\n\nquokka follow-up items\n", encoding="utf-8")
    starter.callback([note])

    async def reindexed() -> bool:
        return (
            await fts_hits(tmp_db_path, "quokka") > 0
            and await fts_hits(tmp_db_path, "zanzibar") == 0
        )

    await wait_until(reindexed)
    await wiring.shutdown()
    assert starter.observer.stopped


async def test_deleted_file_is_removed_from_the_index(tmp_db_path: Path, tmp_path: Path) -> None:
    await apply_migrations(tmp_db_path, MIGRATIONS)  # so the FTS poll can query
    note = tmp_path / "gone.md"
    note.write_text("ephemeral xylophone notes\n", encoding="utf-8")
    starter = FakeWatcherStarter()
    wiring = make_wiring(tmp_db_path, tmp_path, starter)
    wiring.start()
    starter.callback([note])

    async def indexed() -> bool:
        return await fts_hits(tmp_db_path, "xylophone") > 0

    await wait_until(indexed)
    note.unlink()
    starter.callback([note])

    async def removed() -> bool:
        return await fts_hits(tmp_db_path, "xylophone") == 0

    await wait_until(removed)
    await wiring.shutdown()


async def test_no_vault_root_disables_watching_with_an_honest_log_line(
    tmp_db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    starter = FakeWatcherStarter()
    wiring = make_wiring(tmp_db_path, None, starter)
    with caplog.at_level(logging.INFO, logger="engine.wiring.vault_watchdog_server_wiring"):
        wiring.start()
    assert not wiring.is_watching
    assert starter.calls == []  # the starter is never even consulted
    assert "OMNI_VAULT_DIR is not set" in caplog.text
    await wiring.shutdown()  # idempotent no-op


async def test_missing_watchdog_dependency_fails_closed_with_error_log(
    tmp_db_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def raising_starter(vault_root: Path, on_change: Any) -> Any:
        raise IndexDependencyMissingError("the 'watchdog' package is required")

    wiring = VaultWatchdogServerWiring(
        db_path=tmp_db_path,
        migrations_dir=MIGRATIONS,
        vault_root=tmp_path,
        watcher_starter=raising_starter,
        debounce_seconds=0.02,
    )
    with caplog.at_level(logging.ERROR, logger="engine.wiring.vault_watchdog_server_wiring"):
        wiring.start()
    assert not wiring.is_watching  # never pretend watching is active
    assert "watchdog" in caplog.text
    await wiring.shutdown()


async def test_rebind_stops_old_observer_and_starts_on_new_root(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    first = tmp_path / "vault-a"
    second = tmp_path / "vault-b"
    first.mkdir()
    second.mkdir()
    starter = FakeWatcherStarter()
    wiring = make_wiring(tmp_db_path, first, starter)
    wiring.start()
    assert starter.calls == [first]
    first_observer = starter.observer

    await wiring.rebind(second)
    assert first_observer.stopped
    assert wiring.is_watching
    assert starter.calls == [first, second]
    assert starter.observer is not first_observer
    await wiring.shutdown()
