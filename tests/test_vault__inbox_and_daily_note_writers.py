"""Inbox dictation notes and the daily-note appender.

Covers: inbox note shape (date + source: dictation provenance), collision
suffixing, daily-note creation and ordered appends, the configurable daily
folder, missing-trailing-newline completion, multi-line log-forging refusal,
and vault-root env resolution failing closed.
"""

from pathlib import Path

import pytest

from engine.vault.daily_note_appender import append_daily_note_line
from engine.vault.frontmatter_codec import parse_frontmatter
from engine.vault.inbox_dictation_writer import create_inbox_dictation_note
from engine.vault.vault_errors import VaultNotConfiguredError, VaultWriteError
from engine.vault.vault_paths import VAULT_DIR_ENV_VAR, resolve_vault_root


def test_inbox_note_has_date_and_dictation_provenance(tmp_path: Path) -> None:
    path = create_inbox_dictation_note(
        tmp_path,
        title="Idea: local RAG cache",
        body_markdown="Dictated thought about caching 评审 🚀.",
        date_iso="2026-07-06",
    )
    assert path.parent == tmp_path / "Inbox"
    assert path.name == "Idea local RAG cache.md"
    fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert fields == {"date": "2026-07-06", "source": "dictation"}
    assert "Dictated thought about caching 评审 🚀." in body


def test_inbox_same_title_collision_suffixes(tmp_path: Path) -> None:
    first = create_inbox_dictation_note(
        tmp_path, title="Idea", body_markdown="one", date_iso="2026-07-06"
    )
    second = create_inbox_dictation_note(
        tmp_path, title="Idea", body_markdown="two", date_iso="2026-07-06"
    )
    assert first.name == "Idea.md"
    assert second.name == "Idea (2).md"
    assert "one" in first.read_text(encoding="utf-8")
    assert "two" in second.read_text(encoding="utf-8")


def test_daily_note_created_with_header_then_lines_append_in_order(tmp_path: Path) -> None:
    path = append_daily_note_line(
        tmp_path, date_iso="2026-07-06", line="- 09:00 Meeting captured: [[Sync]]"
    )
    append_daily_note_line(
        tmp_path, date_iso="2026-07-06", line="- 10:15 Action executed: calendar event"
    )
    assert path == tmp_path / "Daily" / "2026-07-06.md"
    assert path.read_text(encoding="utf-8") == (
        "# 2026-07-06\n\n"
        "- 09:00 Meeting captured: [[Sync]]\n"
        "- 10:15 Action executed: calendar event\n"
    )


def test_daily_folder_is_configurable_per_call(tmp_path: Path) -> None:
    path = append_daily_note_line(
        tmp_path, date_iso="2026-07-06", line="- entry", daily_folder_name="Journal/Days"
    )
    assert path == tmp_path / "Journal" / "Days" / "2026-07-06.md"
    assert path.exists()


def test_append_completes_a_user_file_missing_trailing_newline(tmp_path: Path) -> None:
    daily = tmp_path / "Daily"
    daily.mkdir(parents=True)
    (daily / "2026-07-06.md").write_bytes(b"user wrote this with no newline")
    append_daily_note_line(tmp_path, date_iso="2026-07-06", line="- omni entry")
    text = (daily / "2026-07-06.md").read_text(encoding="utf-8")
    # User text completed on its own line; our entry never spliced onto it.
    assert text == "user wrote this with no newline\n- omni entry\n"


def test_append_preserves_existing_user_content_byte_exact(tmp_path: Path) -> None:
    daily = tmp_path / "Daily"
    daily.mkdir(parents=True)
    user_bytes = "# My day\r\nuser CRLF line 评审 🚀\r\n".encode()
    (daily / "2026-07-06.md").write_bytes(user_bytes)
    append_daily_note_line(tmp_path, date_iso="2026-07-06", line="- omni entry")
    raw = (daily / "2026-07-06.md").read_bytes()
    assert raw.startswith(user_bytes)
    assert raw == user_bytes + b"- omni entry\n"


def test_multiline_daily_line_is_refused_log_forging_defence(tmp_path: Path) -> None:
    for hostile in ("two\nlines", "cr\rline", "crlf\r\nline"):
        with pytest.raises(VaultWriteError):
            append_daily_note_line(tmp_path, date_iso="2026-07-06", line=hostile)
    assert not (tmp_path / "Daily").exists() or not list((tmp_path / "Daily").iterdir())


def test_no_temp_litter_after_inbox_and_daily_writes(tmp_path: Path) -> None:
    create_inbox_dictation_note(tmp_path, title="T", body_markdown="b", date_iso="2026-07-06")
    append_daily_note_line(tmp_path, date_iso="2026-07-06", line="- x")
    litter = list(tmp_path.rglob(".omni-write-*"))
    assert litter == []


def test_vault_root_env_unset_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VAULT_DIR_ENV_VAR, raising=False)
    with pytest.raises(VaultNotConfiguredError):
        resolve_vault_root()


def test_vault_root_env_blank_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAULT_DIR_ENV_VAR, "   ")
    with pytest.raises(VaultNotConfiguredError):
        resolve_vault_root()


def test_vault_root_env_nonexistent_dir_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(VAULT_DIR_ENV_VAR, str(tmp_path / "missing-vault"))
    with pytest.raises(VaultNotConfiguredError):
        resolve_vault_root()


def test_vault_root_env_existing_dir_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(VAULT_DIR_ENV_VAR, str(tmp_path))
    assert resolve_vault_root() == tmp_path
