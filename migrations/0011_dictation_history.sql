-- Dictation history: every release (inject, note, command) gets a row.
CREATE TABLE IF NOT EXISTS dictation_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('note', 'inject', 'command')),
    raw_text TEXT NOT NULL,
    cleaned_text TEXT,
    note_path TEXT,
    note_title TEXT,
    cleanup_style TEXT,
    stt_engine TEXT
);

CREATE INDEX IF NOT EXISTS idx_dictation_entries_created_at
    ON dictation_entries (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dictation_entries_mode
    ON dictation_entries (mode);
