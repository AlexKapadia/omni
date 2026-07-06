-- 0006_meeting_finalization_columns.sql — M2 finalization state on meetings.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.
--
-- Written once by the meeting finalization service; the Library screen's
-- meetings.list / meeting.get commands read them. notes_text is the user's
-- rough notes EXACTLY as typed (fidelity mandate: byte-identical — the vault
-- note and this column both carry the untouched original).

ALTER TABLE meetings ADD COLUMN note_path TEXT;         -- vault-relative note path
ALTER TABLE meetings ADD COLUMN notes_text TEXT;        -- user notes, verbatim
ALTER TABLE meetings ADD COLUMN enhanced_notes_md TEXT; -- sanitised enhancement output
ALTER TABLE meetings ADD COLUMN finalized_at TEXT;      -- ISO-8601 UTC, NULL until finalized
