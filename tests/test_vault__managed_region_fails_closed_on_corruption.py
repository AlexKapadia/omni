"""Marker corruption refuses the write — and leaves the file on disk untouched.

Fail-closed cases: missing/duplicated/unclosed/out-of-order markers, foreign
markers nested inside the target span, marker text inside code fences
(fence-blind by design: ambiguity refuses, never a wrong-span rewrite), and
replacement text that tries to smuggle marker lines in (region injection).
"""

from pathlib import Path

import pytest

from engine.vault.managed_region_rewriter import (
    REGION_ACTIONS,
    REGION_ENHANCED_NOTES,
    close_marker,
    open_marker,
    rewrite_managed_region,
)
from engine.vault.meeting_note_writer import update_meeting_enhanced_notes
from engine.vault.vault_errors import ManagedRegionCorruptionError

_OPEN = open_marker(REGION_ACTIONS)
_CLOSE = close_marker(REGION_ACTIONS)


def _refuses(content: str) -> None:
    """Assert the rewrite is refused for this file content."""
    with pytest.raises(ManagedRegionCorruptionError):
        rewrite_managed_region(content.encode("utf-8"), REGION_ACTIONS, "new")


def test_zero_markers_refused() -> None:
    _refuses("just some user text\nno markers anywhere\n")


def test_open_without_close_refused() -> None:
    _refuses(f"before\n{_OPEN}\ninner never closed\n")


def test_close_without_open_refused() -> None:
    _refuses(f"before\n{_CLOSE}\nafter\n")


def test_duplicated_open_marker_refused() -> None:
    _refuses(f"{_OPEN}\n{_OPEN}\ninner\n{_CLOSE}\n")


def test_duplicated_close_marker_refused() -> None:
    _refuses(f"{_OPEN}\ninner\n{_CLOSE}\ntrailing\n{_CLOSE}\n")


def test_close_before_open_refused() -> None:
    _refuses(f"{_CLOSE}\ninner\n{_OPEN}\n")


def test_foreign_marker_nested_inside_target_region_refused() -> None:
    """Another region's marker inside the span would be destroyed — refuse."""
    nested = open_marker(REGION_ENHANCED_NOTES)
    _refuses(f"{_OPEN}\n{nested}\n{_CLOSE}\n")


def test_malformed_marker_like_line_inside_region_refused() -> None:
    """Even a malformed marker-like line inside the span is ambiguous."""
    _refuses(f"{_OPEN}\nsome text <!-- omni:managed garbage\n{_CLOSE}\n")


def test_marker_inside_code_fence_counts_and_makes_file_ambiguous() -> None:
    """Fence-blind semantics: a fenced marker duplicates the real one — refuse."""
    _refuses(f"```\n{_OPEN}\n```\n{_OPEN}\nreal inner\n{_CLOSE}\n")


def test_replacement_text_containing_marker_sentinel_refused() -> None:
    """Region injection: replacement may not manufacture or terminate regions."""
    valid = f"{_OPEN}\ninner\n{_CLOSE}\n".encode()
    for hostile in (
        f"{_CLOSE}\nescaped!\n{_OPEN}",
        "text\n<!-- omni:managed:actions -->\ntext",
        "sneaky <!-- /omni:managed:actions --> inline",
    ):
        with pytest.raises(ManagedRegionCorruptionError):
            rewrite_managed_region(valid, REGION_ACTIONS, hostile)


def test_invalid_region_id_refused() -> None:
    valid = f"{_OPEN}\ninner\n{_CLOSE}\n".encode()
    for bad_id in ("", "UPPER", "spaces in id", "trailing-", "-leading", "a_b", "a\n"):
        with pytest.raises(ManagedRegionCorruptionError):
            rewrite_managed_region(valid, bad_id, "new")


def test_region_id_mismatch_refused() -> None:
    """Markers for a different region never satisfy the target region."""
    content = (
        f"{open_marker(REGION_ENHANCED_NOTES)}\ninner\n"
        f"{close_marker(REGION_ENHANCED_NOTES)}\n"
    )
    _refuses(content)


def test_refused_update_leaves_file_on_disk_byte_identical(tmp_path: Path) -> None:
    """End-to-end fail-closed: the note writer refuses AND the file is untouched."""
    note = tmp_path / "corrupt.md"
    # Enhanced Notes region is unclosed — a rewrite would be ambiguous.
    original = (
        "# Title\nuser text 用户文本 🚀\n"
        f"{open_marker(REGION_ENHANCED_NOTES)}\nnever closed\n"
    ).encode()
    note.write_bytes(original)
    with pytest.raises(ManagedRegionCorruptionError):
        update_meeting_enhanced_notes(note, "new enhanced notes")
    assert note.read_bytes() == original
    # No temp-file litter from the refused write.
    assert not list(tmp_path.glob(".omni-write-*"))
