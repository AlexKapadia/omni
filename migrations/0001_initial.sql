-- 0001_initial.sql — core tables for M0.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.
-- schema_migrations bookkeeping is created code-side by the runner.

-- Meetings captured (or to be captured) by the engine.
CREATE TABLE meetings (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    started_at        TEXT NOT NULL,            -- ISO-8601 UTC
    ended_at          TEXT,                     -- NULL while in progress
    calendar_event_id TEXT,                     -- NULL when not calendar-linked
    disclosed         INTEGER NOT NULL DEFAULT 0
                      CHECK (disclosed IN (0, 1))  -- boolean: user disclosed recording
);

-- Transcript segments, labelled per stream:
-- 'me' = microphone (the user), 'them' = WASAPI loopback (other participants).
CREATE TABLE transcript_segments (
    id         TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    stream     TEXT NOT NULL CHECK (stream IN ('me', 'them')),
    text       TEXT NOT NULL,
    t_start    REAL NOT NULL,                   -- seconds from meeting start
    t_end      REAL NOT NULL,
    created_at TEXT NOT NULL                    -- ISO-8601 UTC
);

CREATE INDEX idx_transcript_segments_meeting_id
    ON transcript_segments (meeting_id);

-- Immutable audit trail of every executed action and external call.
CREATE TABLE audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic, gap-revealing
    ts           TEXT NOT NULL,                      -- ISO-8601 UTC
    action       TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json  TEXT
);

-- SECURITY INVARIANT (append-only audit log): the audit trail must be
-- tamper-evident, so mutation is blocked in the SCHEMA itself — no code
-- path, bug, or ad-hoc query can rewrite history. RAISE(ABORT) rolls back
-- the offending statement (fail closed).
CREATE TRIGGER audit_log_block_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER audit_log_block_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is forbidden');
END;
