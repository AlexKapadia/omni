-- 0004_index_layer.sql — M3 "Brain" index layer (AI-facing memory over the vault).
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this file
-- in a single transaction; do NOT add BEGIN/COMMIT here.
--
-- Architecture contract: docs/research/m3-retrieval-architecture-recommendation.md
--   chunks       — heading-aware, contextualized chunks with exact citation spans
--   chunks_fts   — FTS5 external-content index over contextualized_text (BM25 side)
--   entities     — canonical entities (person/company/commitment/date) + aliases
--   entity_mentions — entity <-> chunk join (structural "same entity" graph edges)
--   notes_meta   — per-note frontmatter + change-detection (mtime + content hash)
--   links        — wikilink graph (free structural graph from Obsidian's own links)
--
-- chunks_vec (sqlite-vec vec0) is NOT created here: it requires the sqlite-vec
-- loadable extension, which is not available to the migration runner's plain
-- connection. engine/index/sqlite_vec_store.py creates it idempotently at init.
--
-- SECURITY INVARIANT (local-only): everything indexed here stays on-machine;
-- chunk/entity text is untrusted content and is only ever bound as SQL
-- parameters by the code layer — never interpolated.

-- One row per retrievable chunk. Rows are immutable by design: the indexer
-- re-indexes a note by deleting all its chunks and inserting fresh ones
-- (delete-then-insert, atomic per note), never by UPDATE.
CREATE TABLE chunks (
    id                  INTEGER PRIMARY KEY,     -- rowid; FTS5 external-content key
    note_path           TEXT    NOT NULL,        -- vault-relative posix path, or transcript://<meeting_id>
    source_type         TEXT    NOT NULL CHECK (source_type IN ('vault', 'transcript')),
    note_title          TEXT    NOT NULL,
    heading_path        TEXT    NOT NULL DEFAULT '',  -- ' > '-joined heading breadcrumb
    line_start          INTEGER NOT NULL,        -- 1-based, inclusive (citation contract)
    line_end            INTEGER NOT NULL,        -- 1-based, inclusive
    char_start          INTEGER NOT NULL,        -- 0-based offset into the source document
    char_end            INTEGER NOT NULL,        -- exclusive; text == source[char_start:char_end]
    text                TEXT    NOT NULL,        -- exact source slice (citation fidelity)
    contextualized_text TEXT    NOT NULL,        -- deterministic prefix + text (what gets embedded/BM25'd)
    mtime               REAL    NOT NULL,        -- source file mtime at index time (0.0 for transcripts)
    CHECK (line_end >= line_start),
    CHECK (char_end > char_start)
);

CREATE INDEX idx_chunks_note_path ON chunks (note_path);

-- BM25 side of the hybrid retriever. External-content: FTS5 stores only the
-- inverted index; row text lives in chunks. Kept in lockstep via triggers.
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    contextualized_text,
    note_title,
    heading_path,
    content='chunks',
    content_rowid='id'
);

-- External-content FTS5 is NOT self-maintaining: these triggers are the only
-- sync mechanism. The 'delete' command must replay the OLD row values exactly,
-- or the inverted index silently corrupts.
CREATE TRIGGER chunks_fts_after_insert
AFTER INSERT ON chunks
BEGIN
    INSERT INTO chunks_fts (rowid, contextualized_text, note_title, heading_path)
    VALUES (new.id, new.contextualized_text, new.note_title, new.heading_path);
END;

CREATE TRIGGER chunks_fts_after_delete
AFTER DELETE ON chunks
BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, contextualized_text, note_title, heading_path)
    VALUES ('delete', old.id, old.contextualized_text, old.note_title, old.heading_path);
END;

CREATE TRIGGER chunks_fts_after_update
AFTER UPDATE ON chunks
BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, contextualized_text, note_title, heading_path)
    VALUES ('delete', old.id, old.contextualized_text, old.note_title, old.heading_path);
    INSERT INTO chunks_fts (rowid, contextualized_text, note_title, heading_path)
    VALUES (new.id, new.contextualized_text, new.note_title, new.heading_path);
END;

-- Canonical entities for structured (exact-SQL) lookup and same-entity graph
-- expansion. Populated by the M3 extraction pipeline (engine/agents, later);
-- the index layer reads them and cascades cleanup.
CREATE TABLE entities (
    id             INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL CHECK (entity_type IN ('person', 'company', 'commitment', 'date')),
    aliases_json   TEXT NOT NULL DEFAULT '[]',  -- JSON array of alias strings
    UNIQUE (canonical_name, entity_type)
);

CREATE TABLE entity_mentions (
    id        INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    chunk_id  INTEGER NOT NULL REFERENCES chunks (id) ON DELETE CASCADE,
    UNIQUE (entity_id, chunk_id)
);

CREATE INDEX idx_entity_mentions_chunk_id ON entity_mentions (chunk_id);

-- Per-note metadata: frontmatter fields (JSON), temporal anchors, and the
-- change-detection pair (mtime + content_hash) the incremental indexer keys on.
CREATE TABLE notes_meta (
    note_path        TEXT PRIMARY KEY,           -- matches chunks.note_path
    source_type      TEXT NOT NULL CHECK (source_type IN ('vault', 'transcript')),
    title            TEXT NOT NULL,
    stem             TEXT NOT NULL,              -- lowercased filename stem: wikilink resolution key
    frontmatter_json TEXT NOT NULL DEFAULT '{}', -- lenient-parsed frontmatter, untrusted data
    created          TEXT,                       -- ISO date from frontmatter, when present
    modified         TEXT,                       -- ISO date from frontmatter or file mtime
    mtime            REAL NOT NULL,
    content_hash     TEXT NOT NULL               -- sha256 hex of the source document
);

CREATE INDEX idx_notes_meta_stem ON notes_meta (stem);

-- Wikilink graph. src_note is a note_path; dst_note is the link target
-- normalised to a lowercased note stem (alias and #heading stripped), resolved
-- against notes_meta.stem at query time. Unresolved targets simply match nothing.
CREATE TABLE links (
    src_note TEXT NOT NULL,
    dst_note TEXT NOT NULL,
    PRIMARY KEY (src_note, dst_note)
) WITHOUT ROWID;

CREATE INDEX idx_links_dst_note ON links (dst_note);
