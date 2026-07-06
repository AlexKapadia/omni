-- 0007_dictation_intents.sql — M5 dictation command-mode intents, append-only.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.
--
-- One row per "Omni,"-prefixed dictation release. raw_text is the VERBATIM
-- transcript (fidelity mandate: ground truth, never rewritten); fields_json
-- is the validated intent fields object. M4's approval cards READ these
-- rows; M5 NEVER executes anything — recording is the entire write path
-- (approval-before-execute invariant). provider/model are NULL when the
-- router was down and the intent was recorded as 'unknown' locally.

CREATE TABLE dictation_intents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic, gap-revealing
    ts           TEXT NOT NULL,                      -- ISO-8601 UTC
    raw_text     TEXT NOT NULL,                      -- verbatim dictated text (incl. wake word)
    intent_type  TEXT NOT NULL CHECK (intent_type IN
                     ('create_event','upsert_contact','draft_email','write_note','unknown')),
    fields_json  TEXT NOT NULL,                      -- validated fields{} JSON object
    confidence   REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    provider     TEXT,                               -- which provider parsed it (NULL: router down)
    model        TEXT
);

CREATE INDEX idx_dictation_intents_ts
    ON dictation_intents (ts);

-- SECURITY INVARIANT (append-only): intents feed approval cards, so mutation
-- is blocked in the SCHEMA itself — no code path can rewrite what the user
-- said or what was parsed. RAISE(ABORT) rolls back the statement (fail closed).
CREATE TRIGGER dictation_intents_block_update
BEFORE UPDATE ON dictation_intents
BEGIN
    SELECT RAISE(ABORT, 'dictation_intents is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER dictation_intents_block_delete
BEFORE DELETE ON dictation_intents
BEGIN
    SELECT RAISE(ABORT, 'dictation_intents is append-only: DELETE is forbidden');
END;
