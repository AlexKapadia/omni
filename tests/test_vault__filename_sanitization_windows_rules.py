"""Filename sanitization: Windows-illegal chars, reserved devices, caps, collisions.

Untrusted titles become filenames; these tests prove a hostile or awkward
title can never escape the vault folder, address a DOS device, alias a
different name via trailing dots/spaces, or overwrite an existing note.
"""

from pathlib import Path

import pytest

from engine.vault.filename_sanitizer import (
    next_available_note_path,
    sanitize_filename_stem,
)
from engine.vault.obsidian_wikilink_formatter import format_wikilink

_FORBIDDEN = '<>:"/\\|?*[]#^'


@pytest.mark.parametrize("char", list(_FORBIDDEN))
def test_each_forbidden_character_is_removed(char: str) -> None:
    result = sanitize_filename_stem(f"before{char}after")
    assert char not in result
    assert result == "before after"


def test_path_traversal_title_cannot_escape_the_folder() -> None:
    """A hostile title full of separators flattens to a single path component."""
    result = sanitize_filename_stem("..\\..\\Windows/System32\\evil")
    assert "/" not in result
    assert "\\" not in result
    # Bare dot-names would resolve as directory traversal — both neutralised.
    assert sanitize_filename_stem("..") == "Untitled"
    assert sanitize_filename_stem(".") == "Untitled"


def test_control_characters_removed() -> None:
    result = sanitize_filename_stem("a\x00b\x1fc\x7fd\te")
    assert result == "a b c d e"


@pytest.mark.parametrize(
    "reserved",
    ["CON", "con", "Con", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "lpt9"],
)
def test_reserved_device_names_are_neutralised(reserved: str) -> None:
    result = sanitize_filename_stem(reserved)
    assert result.split(".", 1)[0].upper() not in {reserved.upper()}


def test_reserved_name_with_extension_segment_is_neutralised() -> None:
    """'CON.md' still addresses the CON device — the first segment is what counts."""
    result = sanitize_filename_stem("CON.notes")
    assert result.split(".", 1)[0].upper() != "CON"


def test_com0_and_lpt0_are_not_reserved_and_pass_through() -> None:
    """Boundary-exact: only COM1-9 / LPT1-9 are devices; COM0/LPT0 are legal."""
    assert sanitize_filename_stem("COM0") == "COM0"
    assert sanitize_filename_stem("LPT0") == "LPT0"
    assert sanitize_filename_stem("COM10") == "COM10"


def test_trailing_dots_and_spaces_stripped() -> None:
    """Windows silently drops trailing dots/spaces — we must not alias names."""
    assert sanitize_filename_stem("meeting notes...") == "meeting notes"
    assert sanitize_filename_stem("meeting notes   ") == "meeting notes"
    assert sanitize_filename_stem("dots. and spaces. .. ") == "dots. and spaces"


def test_length_cap_applied_and_no_trailing_dot_after_truncation() -> None:
    long_title = "x" * 50 + "." + "y" * 200
    result = sanitize_filename_stem(long_title, max_length=60)
    assert len(result) <= 60
    assert not result.endswith((".", " "))


def test_empty_and_all_illegal_titles_fall_back_to_untitled() -> None:
    assert sanitize_filename_stem("") == "Untitled"
    assert sanitize_filename_stem("   ") == "Untitled"
    assert sanitize_filename_stem('<>:"/\\|?*') == "Untitled"
    assert sanitize_filename_stem("...") == "Untitled"


def test_unicode_titles_pass_through_untouched() -> None:
    """CJK, emoji, and RTL text are legal on NTFS and must be preserved."""
    assert sanitize_filename_stem("评审会议") == "评审会议"
    assert sanitize_filename_stem("🚀 Launch Review 🎯") == "🚀 Launch Review 🎯"
    assert sanitize_filename_stem("اجتماع أسبوعي") == "اجتماع أسبوعي"
    assert sanitize_filename_stem("פגישה שבועית") == "פגישה שבועית"


def test_whitespace_runs_collapse_to_single_spaces() -> None:
    assert sanitize_filename_stem("a  b\t\tc \t d") == "a b c d"


def test_sanitization_is_idempotent() -> None:
    """Sanitizing a sanitized stem changes nothing (stable link targets)."""
    for title in ("a<b>c", "CON", "评审 🚀", "trailing... ", "x" * 500):
        once = sanitize_filename_stem(title)
        assert sanitize_filename_stem(once) == once


def test_collision_suffixing_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "2026-07-06 Sync.md").write_text("first", encoding="utf-8")
    (tmp_path / "2026-07-06 Sync (2).md").write_text("second", encoding="utf-8")
    result = next_available_note_path(tmp_path, "2026-07-06 Sync")
    assert result.name == "2026-07-06 Sync (3).md"
    assert not result.exists()


def test_collision_check_is_case_insensitive(tmp_path: Path) -> None:
    """NTFS is case-insensitive: 'sync.md' collides with 'Sync.md'."""
    (tmp_path / "sync.md").write_text("existing", encoding="utf-8")
    result = next_available_note_path(tmp_path, "Sync")
    assert result.name == "Sync (2).md"


def test_next_available_path_in_missing_folder_is_the_plain_name(tmp_path: Path) -> None:
    result = next_available_note_path(tmp_path / "nowhere", "Note")
    assert result.name == "Note.md"


def test_wikilink_targets_cannot_forge_links_or_aliases() -> None:
    """Link-breaking chars in targets/aliases are neutralised."""
    assert format_wikilink("A]] [[B") == "[[A B]]"
    assert format_wikilink("Meeting|alias#h^b") == "[[Meeting alias h b]]"
    assert format_wikilink("Plain Meeting") == "[[Plain Meeting]]"
    assert format_wikilink("Note", alias="click | here ]]") == "[[Note|click  here]]"
    assert format_wikilink("Note", alias="Note") == "[[Note]]"
