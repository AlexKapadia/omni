-- 0003_router_ledger.sql — append-only ledger of every external model call.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.

-- One row per provider ATTEMPT (successes and failures alike), written by
-- engine/router/fallback_executor.py via router_ledger_repository.py.
-- Feeds the Settings screen's live cost/latency view.
CREATE TABLE router_ledger (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic, gap-revealing
    ts                TEXT    NOT NULL,                   -- ISO-8601 UTC
    task_type         TEXT    NOT NULL,
    provider          TEXT    NOT NULL,
    model             TEXT    NOT NULL,
    latency_ms        INTEGER NOT NULL CHECK (latency_ms >= 0),
    prompt_tokens     INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL CHECK (completion_tokens >= 0),
    -- Exact decimal STRING (e.g. '0.00217'), summed in Python Decimal.
    -- TEXT on purpose: a REAL column would coerce the money path through
    -- binary floating point (zero-numerical-error rule, claude.md §3.11).
    est_cost_usd      TEXT    NOT NULL,
    outcome           TEXT    NOT NULL CHECK (outcome IN ('ok', 'error')),
    -- Error taxonomy value when outcome='error'; NULL on success.
    error_class       TEXT    CHECK (
                          error_class IN ('auth', 'ratelimit', 'timeout', 'server')
                          OR error_class IS NULL
                      )
);

CREATE INDEX idx_router_ledger_provider ON router_ledger (provider);
CREATE INDEX idx_router_ledger_task_type ON router_ledger (task_type);

-- SECURITY INVARIANT (append-only ledger): like audit_log, the call ledger
-- must be tamper-evident — mutation is blocked in the SCHEMA itself so no
-- code path, bug, or ad-hoc query can rewrite call history. RAISE(ABORT)
-- rolls back the offending statement (fail closed).
CREATE TRIGGER router_ledger_block_update
BEFORE UPDATE ON router_ledger
BEGIN
    SELECT RAISE(ABORT, 'router_ledger is append-only: UPDATE is forbidden');
END;

CREATE TRIGGER router_ledger_block_delete
BEFORE DELETE ON router_ledger
BEGIN
    SELECT RAISE(ABORT, 'router_ledger is append-only: DELETE is forbidden');
END;
