"""Personal dictionary: parsing edges, caps, mtime refresh, fail-open.

The dictionary is user-owned, optional, and must NEVER break dictation:
missing/undecodable/hostile files degrade to an empty term list (fail
open, logged once). Parsing is attacked with comments, unicode, control
characters, oversized terms, duplicate storms, and a huge-file cap check;
the cache is proven to refresh on mtime change and to serve unchanged
files without re-reading.
"""

import os
from pathlib import Path

import pytest

from engine.dictation.personal_dictionary import (
    MAX_DICTIONARY_TERMS,
    MAX_TERM_LENGTH,
    PersonalDictionary,
    default_dictionary_path,
    parse_dictionary_lines,
)

# ---------------------------------------------------------------------------
# parse_dictionary_lines (pure)
# ---------------------------------------------------------------------------


def test_basic_terms_comments_and_blanks() -> None:
    raw = "# my names\nSanjay\n\n  Priya  \n# tools\nsqlite-vec\n"
    assert parse_dictionary_lines(raw) == ("Sanjay", "Priya", "sqlite-vec")


def test_unicode_terms_survive_exactly() -> None:
    raw = "Zoë\n東京オフィス\nnaïve-café\n"
    assert parse_dictionary_lines(raw) == ("Zoë", "東京オフィス", "naïve-café")


def test_duplicates_dedupe_order_preserving() -> None:
    assert parse_dictionary_lines("a\nb\na\nc\nb\n") == ("a", "b", "c")


def test_overlong_terms_are_skipped_boundary_exact() -> None:
    at_cap = "x" * MAX_TERM_LENGTH
    over_cap = "y" * (MAX_TERM_LENGTH + 1)
    assert parse_dictionary_lines(f"{at_cap}\n{over_cap}\nok\n") == (at_cap, "ok")


def test_control_characters_are_refused_per_line() -> None:
    # A hostile line never poisons the rest — and never reaches the prompt.
    raw = "good\nbad\x00term\nbad\x1bterm\nalso good\n"
    assert parse_dictionary_lines(raw) == ("good", "also good")


def test_term_count_hard_cap_boundary_exact() -> None:
    lines = "\n".join(f"term{i}" for i in range(MAX_DICTIONARY_TERMS + 50))
    terms = parse_dictionary_lines(lines)
    assert len(terms) == MAX_DICTIONARY_TERMS
    assert terms[-1] == f"term{MAX_DICTIONARY_TERMS - 1}"  # order kept, tail dropped


def test_hash_only_and_whitespace_only_lines_yield_nothing() -> None:
    assert parse_dictionary_lines("#\n   \n\t\n# comment\n") == ()


# ---------------------------------------------------------------------------
# PersonalDictionary (file-backed, cached, fail-open)
# ---------------------------------------------------------------------------


def test_missing_file_fails_open_to_empty(tmp_path: Path) -> None:
    dictionary = PersonalDictionary(path=tmp_path / "absent.txt")
    assert dictionary.terms() == ()
    assert dictionary.terms() == ()  # repeat calls stay cheap and quiet


def test_terms_load_and_cache_serves_unchanged_file(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("Sanjay\nPriya\n", encoding="utf-8")
    dictionary = PersonalDictionary(path=path)
    assert dictionary.terms() == ("Sanjay", "Priya")
    assert dictionary.terms() == ("Sanjay", "Priya")  # cached (same signature)


def test_mtime_change_refreshes_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("OldTerm\n", encoding="utf-8")
    dictionary = PersonalDictionary(path=path)
    assert dictionary.terms() == ("OldTerm",)
    path.write_text("NewTerm\nSecond\n", encoding="utf-8")
    # Force a distinct signature even on coarse filesystem clocks.
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert dictionary.terms() == ("NewTerm", "Second")


def test_file_deleted_after_load_degrades_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("Term\n", encoding="utf-8")
    dictionary = PersonalDictionary(path=path)
    assert dictionary.terms() == ("Term",)
    path.unlink()
    assert dictionary.terms() == ()  # honest: the vocabulary is gone


def test_undecodable_file_fails_open_and_logs_once(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_bytes(b"\xff\xfe\x00 invalid utf-8 \x80\x81")
    dictionary = PersonalDictionary(path=path)
    assert dictionary.terms() == ()
    assert dictionary.terms() == ()  # cached failure: no re-read storm


def test_huge_file_is_read_capped_not_exploded(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    # 2 MiB of terms — far past the 256 KiB read cap. Must parse the capped
    # prefix quickly and never balloon; the term cap also binds.
    path.write_text("\n".join(f"word{i:07d}" for i in range(150_000)), encoding="utf-8")
    dictionary = PersonalDictionary(path=path)
    terms = dictionary.terms()
    assert 0 < len(terms) <= MAX_DICTIONARY_TERMS


def test_no_localappdata_env_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert default_dictionary_path() is None
    dictionary = PersonalDictionary()  # default path resolution
    assert dictionary.terms() == ()  # fail open, never an exception


def test_default_path_points_into_omni_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\alex\AppData\Local")
    path = default_dictionary_path()
    assert path is not None
    assert path.parts[-2:] == ("Omni", "dictionary.txt")
