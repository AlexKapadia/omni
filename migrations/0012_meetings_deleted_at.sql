-- 0012_meetings_deleted_at.sql — soft-delete for Library privacy purge.
-- Applied by engine/storage/sqlite_migrations_runner.py; no BEGIN/COMMIT.
--
-- Hard-delete of meetings is blocked by append-only extraction_results and
-- approval_cards (FK + DELETE triggers). Soft-delete stamps deleted_at so
-- meetings.list / meeting.get hide the row while provenance stays intact.
-- Kept audio and transcript segments are wiped by the delete service; the
-- vault note is left for the user.

ALTER TABLE meetings ADD COLUMN deleted_at TEXT;
