"""Vault file-watching boundary (watchdog) — interface now, wiring later.

Purpose: the OS-level file-change feed for the incremental indexer. M3's
server wiring (debounce, scheduling onto the event loop) lands later; this
module pins the boundary today so the indexer is built against it and unit
tests never need the real dependency.
Pipeline position: upstream of ``VaultIndexerService.index_changed_files``
— the callback receives changed/deleted markdown paths.

Dependency (LAZY, fail closed): ``watchdog`` is a pending dependency
(docs/progress/pending-deps.txt), imported via ``importlib`` only when a
watcher is actually started; absence raises a clear
``IndexDependencyMissingError`` instead of a bare ImportError.

Security invariant (local-only): watching is read-only observation of the
user's own vault; nothing is transmitted anywhere.
"""

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.index.index_layer_errors import IndexDependencyMissingError

# The callback contract: absolute paths of created/modified/moved/deleted
# markdown files. The consumer (indexer wiring) decides batching/debounce.
VaultChangeCallback = Callable[[list[Path]], None]


def start_vault_file_watcher(vault_root: Path, on_change: VaultChangeCallback) -> Any:
    """Start a recursive watchdog observer over the vault; returns the
    observer (caller owns ``observer.stop()``/``.join()``).

    Only ``*.md`` events are forwarded. Raises
    ``IndexDependencyMissingError`` when watchdog is not installed
    (fail closed — the caller must not believe watching is active).
    """
    try:
        # importlib (not a static import): watchdog is a PENDING dep — see
        # docs/progress/pending-deps.txt — so a static import would trip
        # strict mypy before the orchestrator lands it.
        observers_module = importlib.import_module("watchdog.observers")
        events_module = importlib.import_module("watchdog.events")
    except ImportError as exc:
        raise IndexDependencyMissingError(
            "the 'watchdog' package is required for live vault watching but "
            "is not installed — tracked in docs/progress/pending-deps.txt."
        ) from exc

    handler_base: Any = events_module.FileSystemEventHandler

    class _MarkdownEventForwarder(handler_base):  # type: ignore[misc]
        """Forwards markdown file events to the indexer callback."""

        def on_any_event(self, event: Any) -> None:
            if getattr(event, "is_directory", False):
                return
            paths = [
                Path(p)
                for p in (getattr(event, "src_path", None), getattr(event, "dest_path", None))
                if p and str(p).lower().endswith(".md")
            ]
            if paths:
                on_change(paths)

    observer = observers_module.Observer()
    observer.schedule(_MarkdownEventForwarder(), str(vault_root), recursive=True)
    observer.start()
    return observer
