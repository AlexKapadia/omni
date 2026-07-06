"""Atomic file writes for vault notes (write-then-rename).

Purpose: every byte the vault package puts on disk goes through
``write_file_atomically``: content is written to a temp file in the same
directory, fsynced, closed, then swapped in with ``os.replace``. The target
file is never opened for writing directly.
Pipeline position: the only disk-write primitive used by ``engine.vault``.

Security invariants:
- Crash/interruption safety: the target is either the old file or the new
  file, never a truncated half-write (write-then-rename).
- OneDrive/Obsidian coexistence: we never hold an open handle on the target
  itself; if another process (sync client, editor) holds the target locked
  against replacement, we retry briefly and then fail closed with
  ``VaultFileLockedError`` — original file intact, temp file removed.
- Encoding is UTF-8 without BOM; the writers compose content with LF line
  endings. Bytes passed in are written verbatim (byte-exactness for
  managed-region rewrites depends on this).
"""

import contextlib
import os
import tempfile
import time
from pathlib import Path

from engine.vault.vault_errors import VaultFileLockedError

# Replace-retry policy: OneDrive/AV locks are typically transient (<1s).
DEFAULT_REPLACE_RETRIES = 5
DEFAULT_RETRY_DELAY_SECONDS = 0.1


def read_file_bytes(path: Path) -> bytes:
    """Read a note's raw bytes (shared read — safe while Obsidian has it open)."""
    return path.read_bytes()


def write_file_atomically(
    target: Path,
    content: bytes | str,
    *,
    replace_retries: int = DEFAULT_REPLACE_RETRIES,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> None:
    """Atomically write ``content`` to ``target`` via temp file + ``os.replace``.

    ``str`` content is encoded UTF-8 (no BOM); ``bytes`` are written verbatim.
    Raises ``VaultFileLockedError`` if the target remains locked by another
    process after all retries; in that case the original file is untouched
    and the temp file has been deleted (fail closed, no litter).
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    target.parent.mkdir(parents=True, exist_ok=True)
    # Temp file lives in the SAME directory so os.replace is a same-volume
    # atomic rename (cross-volume moves are copy+delete, not atomic).
    fd, temp_name = tempfile.mkstemp(prefix=".omni-write-", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        try:
            os.write(fd, data)
            os.fsync(fd)  # durability: data on disk before the rename publishes it
        finally:
            os.close(fd)  # never hold handles across the replace (lock avoidance)
        _replace_with_retries(temp_path, target, replace_retries, retry_delay_seconds)
    except BaseException:
        # fail-closed cleanup: a refused/failed write leaves no temp litter.
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise


def _replace_with_retries(
    temp_path: Path, target: Path, replace_retries: int, retry_delay_seconds: float
) -> None:
    """``os.replace`` with brief retries for transient Windows share locks."""
    for attempt in range(replace_retries + 1):
        try:
            os.replace(temp_path, target)
            return
        except PermissionError:
            # Windows: target held without FILE_SHARE_DELETE (sync client /
            # editor save-in-progress). Transient — back off and retry.
            if attempt == replace_retries:
                raise VaultFileLockedError(
                    f"target stayed locked after {replace_retries + 1} attempts: {target}"
                ) from None
            time.sleep(retry_delay_seconds)
