"""Server wiring: vault file-watchdog -> debounced incremental reindexing.

Purpose: keeps the M3 index live against EXTERNAL edits (Obsidian, sync
clients) by wiring ``engine.index.vault_watchdog_file_watcher`` to
``VaultIndexerService``. The watcher module pins the OS boundary; this
wiring owns what it deliberately left to the consumer: thread->loop
hand-off, the 500 ms debounce (editors burst events around atomic saves),
and the per-flush connection lifecycle.
Pipeline position: constructed by ``engine.server``'s app factory
(production only — tests inject a fake watcher starter); started/stopped
in the app lifespan.

Honesty notes:
- No configured vault (OMNI_VAULT_DIR unset/invalid) -> the watcher is OFF
  and says so in one log line; nothing is guessed (fail closed).
- Missing ``watchdog`` package -> the lazy import raises and watching stays
  OFF with an explicit error log — we never pretend to be watching.
- ECHO INDEXING: the watcher module has no ignore-own-writes support, so
  Omni's own note writes re-enter here. The cost is honest and small: the
  indexer's content-hash check turns an already-indexed echo into an
  "unchanged" skip, and not-yet-indexed writes (daily lines, people notes)
  simply become searchable — no suppression machinery is warranted.

Security invariant (local-only): watching and indexing read the user's own
vault into the local SQLite file; nothing leaves the machine.
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from engine.index import VaultIndexerService
from engine.index.index_layer_errors import IndexDependencyMissingError
from engine.index.vault_watchdog_file_watcher import (
    VaultChangeCallback,
    start_vault_file_watcher,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations

logger = logging.getLogger(__name__)

# One indexing pass per editor burst: Obsidian/sync clients emit several
# events per save (temp file dances); 500 ms batches them into one flush.
DEBOUNCE_SECONDS = 0.5

# Injection seam: returns the observer object (owns .stop()/.join()).
WatcherStarter = Any  # Callable[[Path, VaultChangeCallback], observer]


class VaultWatchdogServerWiring:
    """One per engine process; ``start()`` is called from the app lifespan."""

    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        vault_root: Path | None,
        watcher_starter: WatcherStarter = start_vault_file_watcher,
        debounce_seconds: float = DEBOUNCE_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._vault_root = vault_root
        self._watcher_starter = watcher_starter
        self._debounce_seconds = debounce_seconds
        self._pending: set[Path] = set()
        self._observer: Any | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_watching(self) -> bool:
        """True only when a real observer is running (never pretended)."""
        return self._observer is not None

    def start(self) -> None:
        """Start watching, or say honestly why watching is off."""
        if self._vault_root is None:
            # fail closed + honest: no configured vault, no watcher.
            logger.info(
                "vault watcher OFF: OMNI_VAULT_DIR is not set — external "
                "vault edits will not be re-indexed until it is configured"
            )
            return
        self._loop = asyncio.get_running_loop()
        try:
            self._observer = self._watcher_starter(
                self._vault_root, self._on_change_from_watcher_thread
            )
        except IndexDependencyMissingError as error:
            # fail closed: never believe watching is active when it is not.
            logger.error("vault watcher OFF: %s", error)
            return
        logger.info(
            "vault watcher ON over %s (%.0f ms debounce)",
            self._vault_root,
            self._debounce_seconds * 1000,
        )

    # The watcher module's callback contract (runs on the observer THREAD).
    def _on_change_from_watcher_thread(self, paths: list[Path]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return  # shutdown race: late OS events are dropped, not crashed
        loop.call_soon_threadsafe(self._note_changes, tuple(paths))

    def _note_changes(self, paths: tuple[Path, ...]) -> None:
        """Loop-side accumulator; (re)uses one debounce/flush task."""
        self._pending.update(paths)
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.get_running_loop().create_task(
                self._debounce_and_flush(), name="vault-watchdog-flush"
            )

    async def _debounce_and_flush(self) -> None:
        """Wait out the burst, then index everything that accumulated.

        Loops while events keep arriving during a flush so nothing is left
        stranded in ``_pending`` without a task to drain it.
        """
        while self._pending:
            await asyncio.sleep(self._debounce_seconds)
            paths = sorted(self._pending)
            self._pending.clear()
            if not paths:
                continue
            try:
                await self._index_paths(paths)
            except Exception:
                # One bad pass must not end watching; the next burst retries.
                logger.exception("vault watcher indexing pass failed")

    async def _index_paths(self, paths: list[Path]) -> None:
        assert self._vault_root is not None  # noqa: S101 — flushes only run when watching
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            # Dense side stays the documented BM25-only degradation (no
            # embedder/vector store wired yet — same decision as the ask
            # gateway and the finalization indexer).
            indexer = VaultIndexerService(connection, self._vault_root)
            report = await indexer.index_changed_files(paths)
        finally:
            await connection.close()
        logger.info(
            "vault watcher reindexed: indexed=%d unchanged=%d removed=%d chunks=%d",
            report.indexed_notes,
            report.unchanged_notes,
            report.removed_notes,
            report.chunks_written,
        )

    async def shutdown(self) -> None:
        """Stop the observer thread and the flush task (idempotent)."""
        observer, self._observer = self._observer, None
        if observer is not None:
            with contextlib.suppress(Exception):
                observer.stop()
                # join off-loop: the observer is a thread, not a task.
                await asyncio.to_thread(observer.join, 2.0)
        task, self._flush_task = self._flush_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


__all__ = ["DEBOUNCE_SECONDS", "VaultChangeCallback", "VaultWatchdogServerWiring"]
