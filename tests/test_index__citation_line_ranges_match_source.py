"""Citation correctness: cited line ranges must contain the chunk verbatim.

For every chunk the indexer produces from a real (synthetic) source file,
re-open the file, slice ``lines[line_start-1 : line_end]``, and require the
chunk's exact text inside it — the ``note_path · L<a>-<b>`` citation the UI
renders must point at exactly the cited words. Also pins the citation
string format itself (middle dot, en dash).
"""

from pathlib import Path

import aiosqlite

from engine.index.markdown_heading_aware_chunker import chunk_markdown_note
from engine.index.retrieved_chunk_types import format_citation
from engine.index.vault_indexer_service import VaultIndexerService
from engine.storage import apply_migrations, open_sqlite_connection

_MULTI_SECTION_NOTE = """---
title: Project Plan
date: 2026-04-01
---
Preamble before any heading, spanning
two lines.

# Scope
The scope covers capture, transcription, and retrieval.

## Out of scope
Telemetry of any kind. Cloud storage of audio.

# Timeline
Milestone one lands in May.
Milestone two lands in June.
"""


def test_chunk_line_ranges_contain_the_exact_text() -> None:
    document = _MULTI_SECTION_NOTE
    lines = document.split("\n")
    chunks = chunk_markdown_note(document, note_path="plan.md")
    assert len(chunks) >= 4  # preamble + three sections
    for chunk in chunks:
        cited_span = "\n".join(lines[chunk.line_start - 1 : chunk.line_end])
        assert chunk.text in cited_span  # the citation contains the words
        assert chunk.text == document[chunk.char_start : chunk.char_end]


def test_line_ranges_survive_splitting_of_long_sections() -> None:
    body_sentences = "".join(f"Sentence number {i} fills the section. " for i in range(120))
    document = f"# Long\n{body_sentences}"
    lines = document.split("\n")
    chunks = chunk_markdown_note(document, note_path="long.md")
    assert len(chunks) > 1  # long section must have split
    for chunk in chunks:
        cited_span = "\n".join(lines[chunk.line_start - 1 : chunk.line_end])
        assert chunk.text in cited_span


def test_citation_string_format_is_exact() -> None:
    # The en dashes below are the UI contract (U+2013), not typos.
    assert format_citation("notes/plan.md", 4, 9) == "notes/plan.md · L4–9"  # noqa: RUF001
    assert format_citation("transcript://m-1", 1, 1) == "transcript://m-1 · L1–1"  # noqa: RUF001
    assert "–" in format_citation("a.md", 1, 2)  # noqa: RUF001  # en dash present
    assert "-" not in format_citation("a", 1, 2)  # plain hyphen absent


async def test_indexed_chunk_rows_cite_real_file_lines(
    tmp_path: Path, tmp_db_path: Path, real_migrations_dir: Path
) -> None:
    """End-to-end: file on disk → indexer → DB rows → citations verified
    against the file's actual lines."""
    await apply_migrations(tmp_db_path, real_migrations_dir)
    connection: aiosqlite.Connection = await open_sqlite_connection(tmp_db_path)
    try:
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "plan.md"
        note.write_text(_MULTI_SECTION_NOTE, encoding="utf-8")
        await VaultIndexerService(connection, vault).index_changed_files([note])
        cursor = await connection.execute(
            "SELECT text, line_start, line_end FROM chunks WHERE note_path = 'plan.md'"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        assert rows
        file_lines = note.read_text(encoding="utf-8").split("\n")
        for text, line_start, line_end in rows:
            cited_span = "\n".join(file_lines[int(line_start) - 1 : int(line_end)])
            assert str(text) in cited_span
    finally:
        await connection.close()
