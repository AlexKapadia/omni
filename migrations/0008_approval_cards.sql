-- 0008_approval_cards.sql — M4 approval cards: the approval-before-execute
-- invariant, enforced IN THE SCHEMA.
-- Applied by engine/storage/sqlite_migrations_runner.py, which wraps this
-- file in a single transaction; do NOT add BEGIN/COMMIT here.
--
-- One row per suggested action. Cards are BUILT from append-only source rows
-- (extraction_results 0005 / dictation_intents 0007), DECIDED by the user
-- (approve/dismiss), and EXECUTED only by engine/agents/card_executor.py.
-- The legal status machine is:
--
--     pending ──> approved ──> executing ──> executed
--        │                          └──────> failed
--        └─────> dismissed
--
-- ANY other transition — including pending->executed (skipping approval),
-- executed->anything (history rewrite), dismissed->approved (resurrecting a
-- refusal) — is blocked below with RAISE(ABORT). No code path, bug, or ad-hoc
-- query can execute an unapproved card or rewrite a decided one (fail closed).

CREATE TABLE approval_cards (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic, gap-revealing
    meeting_id    TEXT REFERENCES meetings(id),       -- NULL for dictation-sourced cards
    source        TEXT NOT NULL CHECK (source IN ('extraction', 'dictation')),
    source_row_id INTEGER NOT NULL,                   -- row id in the source table
    card_type     TEXT NOT NULL CHECK (card_type IN
                      ('create_event', 'find_slot', 'upsert_contact',
                       'write_note', 'draft_email')),
    payload_json  TEXT NOT NULL,                      -- validated typed card payload
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                      ('pending', 'approved', 'executing', 'executed',
                       'failed', 'dismissed')),
    created_at    TEXT NOT NULL,                      -- ISO-8601 UTC
    decided_at    TEXT,                               -- set on approve/dismiss
    executed_at   TEXT,                               -- set on executed/failed
    result_json   TEXT,                               -- tool result on success
    error         TEXT                                -- plain-voice reason on failure
);

CREATE INDEX idx_approval_cards_status ON approval_cards (status);
CREATE INDEX idx_approval_cards_source ON approval_cards (source, source_row_id);
CREATE INDEX idx_approval_cards_meeting_id ON approval_cards (meeting_id);

-- SECURITY INVARIANT (approval-before-execute): every card is BORN pending.
-- Inserting a pre-approved/pre-executed card would bypass the user entirely.
CREATE TRIGGER approval_cards_insert_must_be_pending
BEFORE INSERT ON approval_cards
WHEN NEW.status <> 'pending'
BEGIN
    SELECT RAISE(ABORT,
        'approval_cards: cards must be inserted with status ''pending'' (approval-before-execute)');
END;

-- SECURITY INVARIANT (status machine): only the four legal transitions may
-- ever run. This trigger fires on EVERY update, so a statement that does not
-- perform a legal transition — including a no-op same-status update on a
-- terminal row — aborts. Terminal states (executed/failed/dismissed) are
-- therefore immutable by construction.
CREATE TRIGGER approval_cards_enforce_status_transitions
BEFORE UPDATE ON approval_cards
WHEN NOT (
       (OLD.status = 'pending'   AND NEW.status IN ('approved', 'dismissed'))
    OR (OLD.status = 'approved'  AND NEW.status = 'executing')
    OR (OLD.status = 'executing' AND NEW.status IN ('executed', 'failed'))
)
BEGIN
    SELECT RAISE(ABORT,
        'approval_cards: illegal status transition — allowed: pending->approved|dismissed, approved->executing, executing->executed|failed');
END;

-- AUDITABILITY: a decision without a decision time is an incomplete record.
CREATE TRIGGER approval_cards_decision_requires_decided_at
BEFORE UPDATE ON approval_cards
WHEN NEW.status IN ('approved', 'dismissed') AND NEW.decided_at IS NULL
BEGIN
    SELECT RAISE(ABORT,
        'approval_cards: decided_at must be set when approving or dismissing');
END;

-- AUDITABILITY: an execution outcome without its timestamp is incomplete.
CREATE TRIGGER approval_cards_outcome_requires_executed_at
BEFORE UPDATE ON approval_cards
WHEN NEW.status IN ('executed', 'failed') AND NEW.executed_at IS NULL
BEGIN
    SELECT RAISE(ABORT,
        'approval_cards: executed_at must be set when recording an outcome');
END;

-- SECURITY INVARIANT (provenance immutability): which source row produced a
-- card, its type, and its birth time can never be rewritten — the card's
-- lineage back to the append-only source tables must stay tamper-evident.
CREATE TRIGGER approval_cards_provenance_immutable
BEFORE UPDATE ON approval_cards
WHEN NEW.id <> OLD.id
  OR NEW.meeting_id IS NOT OLD.meeting_id
  OR NEW.source <> OLD.source
  OR NEW.source_row_id <> OLD.source_row_id
  OR NEW.card_type <> OLD.card_type
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT,
        'approval_cards: provenance columns are immutable');
END;

-- SECURITY INVARIANT (what-you-approved-is-what-executes): the payload may
-- change only while pending (the user's pre-approval edit riding the approve
-- statement). After the decision it is frozen — execution can never act on
-- data the user did not see and approve.
CREATE TRIGGER approval_cards_payload_locked_after_decision
BEFORE UPDATE ON approval_cards
WHEN OLD.status <> 'pending' AND NEW.payload_json <> OLD.payload_json
BEGIN
    SELECT RAISE(ABORT,
        'approval_cards: payload is locked after the approval decision');
END;

-- SECURITY INVARIANT (append-only decisions): cards are dismissed, never
-- deleted — a vanished card would hide that an action was ever suggested.
CREATE TRIGGER approval_cards_block_delete
BEFORE DELETE ON approval_cards
BEGIN
    SELECT RAISE(ABORT, 'approval_cards: DELETE is forbidden — dismiss instead (auditability)');
END;
