-- 0005_extraction_results.sql — M2 meeting-extraction output, append-only.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.
--
-- One row per extraction pass over a finalised meeting. payload_json is the
-- validated MeetingExtraction JSON (actions / contacts / dates /
-- open_questions / commitments). M4's approval cards READ these rows; they
-- are never edited — a re-run appends a newer row (latest ts wins).

CREATE TABLE extraction_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic, gap-revealing
    meeting_id   TEXT NOT NULL REFERENCES meetings(id),
    ts           TEXT NOT NULL,                      -- ISO-8601 UTC
    payload_json TEXT NOT NULL                       -- validated extraction JSON
);

CREATE INDEX idx_extraction_results_meeting_id
    ON extraction_results (meeting_id);

-- SECURITY INVARIANT (append-only): extraction results feed approval cards,
-- so mutation is blocked in the SCHEMA itself — no code path can rewrite
-- what was extracted. RAISE(ABORT) rolls back the statement (fail closed).
CREATE TRIGGER extraction_results_block_update
BEFORE UPDATE ON extraction_results
BEGIN
    SELECT RAISE(ABORT, 'extraction_results is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER extraction_results_block_delete
BEFORE DELETE ON extraction_results
BEGIN
    SELECT RAISE(ABORT, 'extraction_results is append-only: DELETE is forbidden');
END;
