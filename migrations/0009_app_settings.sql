-- 0009_app_settings.sql — M7 app settings: one key-value row per setting,
-- with an APPEND-ONLY history trail of every change.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.
--
-- Written ONLY through engine/storage/app_settings_repository.py (which
-- validates keys/values first — deny by default on unknown settings keys).
-- Values are JSON so booleans/lists/objects round-trip exactly.
--
-- AUDIT INVARIANT: app_settings itself is mutable (it is "current state"),
-- but every INSERT/UPDATE is mirrored into app_settings_history by the
-- triggers below, and the history table is append-only (UPDATE/DELETE are
-- blocked in the SCHEMA with RAISE(ABORT), same pattern as audit_log /
-- router_ledger). No code path can change a setting without leaving a row.

CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY,   -- settings key (validated in the repository)
    value_json TEXT NOT NULL,      -- JSON-encoded value (exact round-trip)
    updated_at TEXT NOT NULL       -- ISO-8601 UTC of the last change
);

CREATE TABLE app_settings_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic, gap-revealing
    key        TEXT NOT NULL,
    value_json TEXT NOT NULL,
    changed_at TEXT NOT NULL       -- copied from app_settings.updated_at
);

-- Every settings write leaves a history row (audit-friendly by construction).
CREATE TRIGGER app_settings_history_on_insert
AFTER INSERT ON app_settings
BEGIN
    INSERT INTO app_settings_history (key, value_json, changed_at)
    VALUES (NEW.key, NEW.value_json, NEW.updated_at);
END;

CREATE TRIGGER app_settings_history_on_update
AFTER UPDATE ON app_settings
BEGIN
    INSERT INTO app_settings_history (key, value_json, changed_at)
    VALUES (NEW.key, NEW.value_json, NEW.updated_at);
END;

-- SECURITY INVARIANT (append-only history): tamper-evidence lives in the
-- schema itself — RAISE(ABORT) rolls back any mutation attempt (fail closed).
CREATE TRIGGER app_settings_history_block_update
BEFORE UPDATE ON app_settings_history
BEGIN
    SELECT RAISE(ABORT, 'app_settings_history is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER app_settings_history_block_delete
BEFORE DELETE ON app_settings_history
BEGIN
    SELECT RAISE(ABORT, 'app_settings_history is append-only: DELETE is forbidden');
END;
