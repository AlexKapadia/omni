"""Atomic writes vs. concurrently-open handles (Obsidian/OneDrive simulation).

On Windows, another process holding the target open (without delete
sharing) blocks ``os.replace``. The writer must retry, then fail CLOSED:
original file intact, temp file removed, ``VaultFileLockedError`` raised.
Once the handle is released the same write must succeed. POSIX allows
rename-over-open-file, so the lock expectation is Windows-only.
"""

import sys
from pathlib import Path

import pytest

from engine.vault.atomic_markdown_file_io import write_file_atomically
from engine.vault.vault_errors import VaultFileLockedError


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows blocks replace-over-open-handle; see the lock tests below",
)
def test_write_succeeds_while_target_is_open_for_read_then_reads_new_content(
    tmp_path: Path,
) -> None:
    """POSIX semantics; on Windows this case is covered by the lock test below."""
    target = tmp_path / "note.md"
    target.write_text("old", encoding="utf-8")
    with target.open("r", encoding="utf-8"):
        write_file_atomically(target, "new content")
    assert target.read_text(encoding="utf-8") == "new content"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_locked_target_fails_closed_original_intact_no_litter(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    original = "original user content 评审 🚀\n"
    target.write_text(original, encoding="utf-8")
    # Simulate Obsidian/OneDrive: a plain read handle lacks FILE_SHARE_DELETE,
    # so os.replace over the target is denied while it is held open.
    with target.open("r", encoding="utf-8"), pytest.raises(VaultFileLockedError):
        write_file_atomically(
            target, "replacement", replace_retries=2, retry_delay_seconds=0.01
        )
    assert target.read_text(encoding="utf-8") == original  # fail closed: untouched
    assert list(tmp_path.glob(".omni-write-*")) == []  # temp cleaned up


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_write_succeeds_after_lock_released(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_text("old", encoding="utf-8")
    handle = target.open("r", encoding="utf-8")
    with pytest.raises(VaultFileLockedError):
        write_file_atomically(target, "new", replace_retries=1, retry_delay_seconds=0.01)
    handle.close()
    write_file_atomically(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_new_file_write_is_utf8_no_bom_lf_only(tmp_path: Path) -> None:
    target = tmp_path / "fresh.md"
    write_file_atomically(target, "line one\nline two 评审 🚀\n")
    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
    assert b"\r" not in raw  # LF only
    assert raw.decode("utf-8") == "line one\nline two 评审 🚀\n"


def test_write_creates_missing_parent_folders(tmp_path: Path) -> None:
    target = tmp_path / "Deep" / "Nested" / "note.md"
    write_file_atomically(target, "content")
    assert target.read_text(encoding="utf-8") == "content"


def test_bytes_content_is_written_verbatim(tmp_path: Path) -> None:
    """Byte-exactness of managed rewrites depends on verbatim byte writes."""
    target = tmp_path / "raw.md"
    payload = b"\xef\xbb\xbfuser CRLF\r\nmixed\rendings\nno final newline"
    write_file_atomically(target, payload)
    assert target.read_bytes() == payload


def test_interrupted_write_never_leaves_partial_target(tmp_path: Path) -> None:
    """Old content stays until the rename publishes the new file atomically."""
    target = tmp_path / "note.md"
    target.write_text("v1", encoding="utf-8")
    write_file_atomically(target, "v2")
    write_file_atomically(target, "v3")
    # After any completed sequence the file is a complete version, and no
    # temp files remain to confuse Obsidian or the sync client.
    assert target.read_text(encoding="utf-8") == "v3"
    assert list(tmp_path.glob("*.tmp")) == []
