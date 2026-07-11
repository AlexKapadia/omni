# Contributing to Omni

Thanks for being here. Omni is a local-first, bot-free meeting-intelligence engine (Windows first-class; macOS and Linux bundles supported), and it is genuinely fun to extend — most of all by teaching the voice agent (Naomi) and the approval system **new things they can do**. "Naomi, set a timer." "Remind me to call the dentist tomorrow." "What's the weather in Lisbon?" Every one of those is a small, well-scoped tool that plugs into an extension point that already exists. This guide shows you exactly where it plugs in.

Before anything else, one promise you're agreeing to uphold: **Omni never betrays the user's trust.** It runs on their machine, joins nothing, uploads nothing they didn't ask it to, and never executes an action without their approval. That is the whole product. A contribution that weakens it — however clever — will be turned down, kindly but firmly (see [Non-negotiables](#non-negotiables)). Everything else, we'd love your help with.

- [The promise your code must keep](#the-promise-your-code-must-keep)
- [Dev setup](#dev-setup)
- [Running the gate](#running-the-gate)
- [★ Add a new ability (agent tool) — the star tutorial](#-add-a-new-ability-agent-tool)
- [Non-negotiables](#non-negotiables)
- [Branch, commit, and PR flow](#branch-commit-and-pr-flow)
- [License and sign-off](#license-and-sign-off)

---

## The promise your code must keep

Omni is built to an institution-grade bar: production-grade, secure by default, and fully tested. These invariants are enforced in code (SQL triggers, pydantic models, source-scanning tests), not by convention — so if your change tries to break one, a test or the schema will stop you. That's the safety net working, not an obstacle.

- **Local-first.** Transcripts, embeddings, notes, and keys never leave the machine — except the minimum excerpt inside a model call the user configured. Audio is kept on-device as MP3 alongside the transcript by default (the user can opt out to discard after transcription); either way it never leaves the machine.
- **Zero telemetry.** No phone-home. Ever. Not for crash reports, not for "anonymous usage", not for anything.
- **Approval-before-execute.** No calendar event, contact upsert, vault write, or draft happens without an approved card. Deny by default.
- **Draft-only for anything outbound.** Gmail is the precedent: Omni drafts, it never sends. A new tool that dispatches on the user's behalf is not welcome — draft it, or propose it and let the user pull the trigger.
- **Keys via Windows DPAPI, held only by the engine.** Never plaintext on disk, never logged, never in the UI process.
- **Every executed action is audited** — append-only, one row per attempt: what ran, when, which provider, and exactly what data left the machine.

If your feature can live inside these lines, it belongs in Omni. If it can't, it belongs in a fork.

---

## Dev setup

Omni is two processes: a **Tauri 2 shell + React front end** (`apps/ui/`) that only renders state and relays commands, and a **Python engine sidecar** (`engine/`) that does all the real work over a localhost WebSocket. In dev, `pnpm tauri dev` boots both.

**Prerequisites**

- **[uv](https://docs.astral.sh/uv/)** — the Python toolchain. It provisions Python 3.11 itself; you don't need a system Python.
- **[pnpm](https://pnpm.io/)** — for the front end.
- **Rust toolchain** — what Tauri builds against. Windows: MSVC ([portable MSVC](https://tauri.app/start/prerequisites/) works). macOS/Linux: see [Tauri prerequisites](https://tauri.app/start/prerequisites/).

```bash
git clone https://github.com/AlexKapadia/omni
cd omni

# Engine — install deps (uv provisions Python 3.11 for you)
uv sync

# Front end
cd apps/ui && pnpm install

# Run the whole app (Tauri boots the engine sidecar for you)
pnpm tauri dev
```

Prefer the pieces separately? `uv run python -m engine.server` starts just the engine (`GET http://127.0.0.1:8765/health` → `{"status":"ok"}`), and `pnpm dev` in `apps/ui` runs the UI against it.

**Keys.** Omni is bring-your-own-keys — no backend, no accounts. You don't need any key to work on the engine's local paths (capture, storage, indexing, the vault, most of the approval flow). For features that call a provider, add a key through the in-app onboarding wizard, where it's DPAPI-encrypted on the spot. Never put a key in a file, a test, or a commit. Tests never touch the network — they mock providers and the Google gateway.

**Where things live** (the directory layout mirrors the data flow):

```
apps/ui/            # Tauri 2 shell + React front end — renders state, relays commands
engine/
  audio/            # WASAPI (Windows) + sounddevice cross-platform capture
  stt/              # Silero VAD + Parakeet / Whisper / BYOK backends
  index/            # markdown chunker, bge-small embedder, sqlite-vec store
  router/           # provider clients, routing table, cost/latency ledger
  agents/           # ← the approval tools live here (this is where you'll work)
  naomi/            # the voice agent's turn loop
  dictation/        # push-to-talk sessions, cleanup styles, history
  enhance/          # enhanced notes, meeting finalization
  export/           # PDF/DOCX and document export helpers
  vault/            # markdown writers, frontmatter, managed markers
  storage/          # SQLite connection + migrations runner
migrations/         # numbered .sql schema migrations
tests/              # pytest (engine) — one file per behaviour
docs/               # architecture, features, plans — see docs/README.md
```

---

## Running the gate

Everything that lands on `main` is green. Run the full gate locally **before you push** — CI runs the same commands on Linux, and a lint rule the test run never exercised has gone red on people before.

```bash
# Engine (from the repo root)
uv run ruff check .        # lint + import order + security lints (S rules)
uv run mypy                # strict type-checking on engine + tests
uv run pytest              # the whole suite (no network, synthetic data only)

# Front end (from apps/ui)
pnpm run typecheck         # tsc --noEmit
pnpm run test              # vitest run
```

The bar every change is held to:

- **Files stay ≤ 300 lines.** One clear responsibility per file. If a file needs "and" to describe it, split it. Names say exactly what's inside — `reminder_create_tool.py`, never `utils.py`.
- **Tests have teeth.** Adversarial, boundary-exact, property-based where it fits — not happy-path, and never a test whose only job is to go green. If everything passes on the first try, assume the tests are too easy and make them harder. A test that couldn't fail if the code were wrong is worse than no test.
- **Coverage clears the gate** — line ≥ 90%, branch ≥ 85% on engine code.
- **Security invariants hold.** The [non-negotiables](#non-negotiables) below are enforced by tests; don't weaken a test to get past them. Fix the code or the design.

---

## ★ Add a new ability (agent tool)

This is the fun part, and it's the thing the project most wants your help with. An "ability" is an **agent tool**: a small, typed unit of work Omni can propose as an approval card and — once the user approves it — execute, audit, and (if you wire the voice path) trigger by talking to Naomi.

The engine ships **five tools today**, and they're your living reference. Read them side-by-side with this tutorial:

| Tool file | Card type | What it does |
| --- | --- | --- |
| `engine/agents/calendar_create_event_tool.py` | `create_event` | Creates one Google Calendar event |
| `engine/agents/calendar_find_free_slot_tool.py` | `find_slot` | Finds a free calendar slot (read-only) |
| `engine/agents/contacts_upsert_tool.py` | `upsert_contact` | Saves a person to the vault, optional Google sync |
| `engine/agents/vault_write_note_tool.py` | `write_note` | Writes a new note to the vault (local-only) |
| `engine/agents/gmail_create_draft_tool.py` | `draft_email` | Creates a Gmail **draft** (never sends) |

We'll build a real sixth one end-to-end: **`create_reminder`** — *"Naomi, remind me to call the dentist tomorrow."* It's local-only (writes a reminder note to the vault), works offline and with the kill-switch engaged, and touches every part of the pipeline, so it's the perfect teaching example. Everything below is real, pasteable code that matches the actual APIs.

### How a tool becomes an action

Here's the whole path, so the steps make sense:

```
   Naomi hears an utterance ──► intent parser ──► PENDING approval card ──► user approves
   (or a meeting extraction)                      (SQL: born 'pending')          │
                                                                                 ▼
                                          card_executor claims it (approved→executing)
                                                   │
                                    maps the card payload ──► tool params
                                                   │
                                          tool.execute(params) runs the real action
                                                   │
                              one append-only audit row + vault trace + status→executed
```

Two things never change no matter what your tool does: **a card is born `pending` and cannot execute until the user approves it** (enforced by SQL triggers in `migrations/0008_approval_cards.sql`, not by app code you could get wrong), and **every execution writes exactly one audit row** (in `engine/agents/card_executor.py`). You get those for free by plugging into the extension point. Your job is the typed tool and its wiring.

### The steps

Adding a **voice-invokable** ability touches about ten spots across two files with SQL `CHECK` constraints. That sounds like a lot; it's really a checklist, and most steps are three lines. (An ability that's only proposed from meeting extraction — not spoken to Naomi — skips steps 6–8.)

1. Add the card type to the `CardType` enum and give it a payload model.
2. Register the payload model so stored cards validate.
3. Write the tool: params model + `dry_run` preview + `execute`.
4. Register the tool in the default registry.
5. Teach the card→params mapper how to translate your payload.
6. Add the intent type so Naomi can classify the request.
7. Map the dictation intent onto your card.
8. Give Naomi a line to speak when she's prepared the card.
9. Widen the two `CHECK` constraints with a migration (the involved one — read it carefully).
10. Write adversarial tests, and update the deliberate "count" guards.

---

#### Step 1 — Card type + payload model

In `engine/agents/approval_card_types.py`, add your value to the `CardType` enum and a payload model. Payloads are built from **untrusted** model output, so every field is bounded and `extra="forbid"` rejects any key you didn't declare — a payload either validates exactly or the card is refused.

```python
class CardType(StrEnum):
    CREATE_EVENT = "create_event"
    FIND_SLOT = "find_slot"
    UPSERT_CONTACT = "upsert_contact"
    WRITE_NOTE = "write_note"
    DRAFT_EMAIL = "draft_email"
    CREATE_REMINDER = "create_reminder"  # ← new


class CreateReminderCardPayload(BaseModel):
    """A proposed reminder note (engine.vault only — no egress at all)."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=_LONG)          # what to be reminded of
    due_hint: str | None = Field(default=None, max_length=_SHORT)  # raw NL time, e.g. "tomorrow 9am"
```

Then add it to the `CardPayload` union and the lookup table in the same file:

```python
CardPayload = (
    CreateEventCardPayload
    | FindSlotCardPayload
    | UpsertContactCardPayload
    | WriteNoteCardPayload
    | DraftEmailCardPayload
    | CreateReminderCardPayload  # ← new
)

PAYLOAD_MODEL_BY_CARD_TYPE: dict[CardType, type[BaseModel]] = {
    # ...existing entries...
    CardType.CREATE_REMINDER: CreateReminderCardPayload,  # ← new
}
```

`_SHORT` (200) and `_LONG` (500) are the existing bounds constants at the top of that file. Reuse them; don't invent new magic numbers.

#### Step 2 — (done in Step 1)

Registering the payload in `PAYLOAD_MODEL_BY_CARD_TYPE` is what lets `parse_card_payload` validate a stored card of your type before it ever reaches your tool. That's the whole of step 2 — you already did it above.

#### Step 3 — The tool

Create `engine/agents/reminder_create_tool.py` (a new ≤300-line file, self-documenting name). This mirrors `vault_write_note_tool.py` almost exactly — it's the closest living example, so read that file alongside this. Every import and helper below is real.

```python
"""Tool: save an approved reminder as a new vault note (local-only, no Google).

Purpose: land an approved "remind me to X" action as a NEW note in the vault
Inbox, with the due-time hint preserved verbatim. Purely local — this tool
has no Google surface and keeps working with the kill switch engaged (fail
closed on egress, never on the user's own data).
Pipeline position: registered in ``tool_registry`` for ``create_reminder``;
uses the same atomic-write / sanitizer primitives as the note-writing tool.

Security invariant: creation-only — collision suffixing means an existing
note is never overwritten (never-edit-user-content).
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from engine.agents.agents_errors import ToolExecutionError
from engine.agents.approval_card_types import CardType
from engine.agents.tool_registry import AgentTool, ToolResult
from engine.google.google_session import GoogleSession
from engine.vault.atomic_markdown_file_io import write_file_atomically
from engine.vault.filename_sanitizer import next_available_note_path, sanitize_filename_stem
from engine.vault.frontmatter_codec import emit_frontmatter
from engine.vault.vault_paths import INBOX_FOLDER, ensure_vault_subfolder


class ReminderCreateParams(BaseModel):
    """A reminder's text and optional due-time hint, exactly as approved."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    due_hint: str | None = Field(default=None, max_length=200)


def _narrow(params: BaseModel) -> ReminderCreateParams:
    """Fail-closed narrowing: the registry pairs params to tools by
    construction, but a mismatch must refuse, never mis-execute."""
    if not isinstance(params, ReminderCreateParams):
        raise ToolExecutionError(
            "ReminderCreateParams", f"expected ReminderCreateParams, got {type(params).__name__}"
        )
    return params


class ReminderCreateTool(AgentTool):
    """Creates ``Inbox/{text}.md`` tagged as a reminder, with an honest source."""

    name = "reminder_create"
    card_type = CardType.CREATE_REMINDER
    params_model = ReminderCreateParams
    description = (
        "Save one reminder as a new markdown note in the vault Inbox, keeping "
        "the due-time hint. Local only; never overwrites an existing note."
    )

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def dry_run(self, params: BaseModel) -> tuple[str, ...]:
        """The card preview: exactly what will be saved, nothing implied."""
        params = _narrow(params)
        lines = [f"Reminder: {params.text}"]
        if params.due_hint:
            lines.append(f"Due: {params.due_hint}")
        lines.append("Saved to Inbox/ (local only)")
        return tuple(lines)

    async def execute(self, params: BaseModel, google_session: GoogleSession) -> ToolResult:
        params = _narrow(params)
        folder = ensure_vault_subfolder(self._vault_root, INBOX_FOLDER)
        # Untrusted text -> sanitized stem; collisions get " (n)" suffixes so
        # nothing is ever overwritten (never-edit-user-content).
        path = next_available_note_path(folder, sanitize_filename_stem(params.text))
        date_iso = datetime.now(tz=UTC).date().isoformat()
        frontmatter = emit_frontmatter(
            {"date": date_iso, "source": "approved-card", "type": "reminder", "due": params.due_hint or ""}
        )
        body = f"# Reminder\n\n{params.text}\n"
        write_file_atomically(path, f"{frontmatter}\n{body}")
        return ToolResult(
            summary_line=f"Reminder saved: {path.name}",
            detail={"note_path": str(path)},
            data_sent_off_machine="",  # local-only invariant: nothing egressed
        )
```

Two things to notice, because they're the pattern for *every* tool:

- **`dry_run` is pure** — no side effects, no network. It renders the exact lines the approval card shows the user. What they see is what executes.
- **`data_sent_off_machine`** is your honest, human-readable account of what left the box. For a local tool it's the empty string; the executor writes it straight into the audit log. If your tool calls a provider, this is where you state — plainly — exactly which fields went where (see how `calendar_create_event_tool.py` and `gmail_create_draft_tool.py` phrase theirs).

#### Step 4 — Register the tool

In `engine/agents/default_tool_registry.py`, import your tool and add it to the tuple. The registry refuses two tools claiming one card type, so this is also where a copy-paste mistake gets caught.

```python
from engine.agents.reminder_create_tool import ReminderCreateTool  # ← new import

def build_default_tool_registry(vault_root: Path) -> ToolRegistry:
    return ToolRegistry(
        (
            CalendarCreateEventTool(),
            CalendarFindFreeSlotTool(),
            ContactsUpsertTool(vault_root),
            VaultWriteNoteTool(vault_root),
            GmailCreateDraftTool(),
            ReminderCreateTool(vault_root),  # ← new
        )
    )
```

#### Step 5 — Map the card payload to tool params

`engine/agents/card_to_tool_params_mapper.py` translates a validated card payload into concrete tool params **without a model** whenever it can (exact, free, and impossible to prompt-inject). For a reminder there's nothing ambiguous to resolve — the mapping is 1:1 — so add an explicit branch:

```python
from engine.agents.approval_card_types import (
    # ...existing imports...
    CreateReminderCardPayload,
)
from engine.agents.reminder_create_tool import ReminderCreateParams


def map_card_payload_to_tool_params(payload: CardPayload) -> MappingOutcome:
    # ...existing isinstance branches...
    if isinstance(payload, CreateReminderCardPayload):
        # 1:1 — there is nothing to "resolve", so never fall to the LLM.
        return _mapped(ReminderCreateParams(text=payload.text, due_hint=payload.due_hint))
    # Exhaustive over CardPayload: the remaining member is draft_email.
    return _map_draft_email(payload)
```

> When *would* you return `_ambiguous(reason)` instead? When a field is natural language that symbolic code can't resolve without inventing meaning — a date like "Friday at 1", or a recipient that's a bare name, not an address. See `_map_create_event` and `_map_draft_email` for exactly how that fallback is drawn, and why the executor then hands those (and only those) cases to the router. A reminder's due-time stays a *hint* on the note, so it never needs resolving — keep it deterministic.

At this point your tool works end-to-end for a card built from a **meeting extraction**. To make it something a user can **say to Naomi**, do steps 6–8.

#### Step 6 — Add the intent type

In `engine/dictation/dictation_intent_schema.py`, add your value to `DictationIntentType` (the JSON schema handed to the router derives its enum from this automatically) and name it in the system frame so the parser knows the category exists:

```python
class DictationIntentType(StrEnum):
    CREATE_EVENT = "create_event"
    UPSERT_CONTACT = "upsert_contact"
    DRAFT_EMAIL = "draft_email"
    WRITE_NOTE = "write_note"
    CREATE_REMINDER = "create_reminder"  # ← new
    UNKNOWN = "unknown"
```

In the same file, add `create_reminder` to the list of intents named in `INTENT_PARSING_SYSTEM_FRAME` (a one-line edit) so the model is told it's a valid classification. Note the dictated text always travels as **data**, never concatenated into that frame — that's the prompt-injection boundary; keep it that way.

#### Step 7 — Map the dictation intent onto your card

In `engine/agents/dictation_intent_card_builder.py`, wire the intent type to your card type and describe how to pull fields out (deterministically — only what the parser extracted or the verbatim text):

```python
_INTENT_TYPE_TO_CARD_TYPE: dict[str, CardType] = {
    # ...existing...
    "create_reminder": CardType.CREATE_REMINDER,  # ← new
}
```

Then add a branch to `_dictation_payload`:

```python
    if card_type is CardType.CREATE_REMINDER:
        text = (
            _clean_str(fields.get("text"), max_length=500)
            or _clean_str(fields.get("task"), max_length=500)
            or _clean_str(record.raw_text, max_length=500)
        )
        if text is None:
            return None  # a reminder with nothing to remember is unactionable
        when_parts = [
            part
            for key in ("when", "date", "time", "due")
            if (part := _clean_str(fields.get(key))) is not None
        ]
        return CreateReminderCardPayload(
            text=text, due_hint=" ".join(when_parts) if when_parts else None
        )
```

(`_clean_str` is the shared helper — a trimmed non-empty string or `None`, no coercion. The other branches in this file are your template.)

The action verb "remind" is **already** in Naomi's action-verb pre-filter (`_ACTION_LEAD_TOKENS` in `engine/naomi/naomi_action_intent_flow.py`), so *"Remind me to…"* already routes to the intent parser instead of being answered as a question. If your verb isn't in that set, add it there.

#### Step 8 — Give Naomi something to say

In `engine/naomi/naomi_action_intent_flow.py`, add a confirmation line so Naomi tells the user she prepared the card (she never executes it — she only prepares a `pending` card and says so):

```python
_CONFIRMATION_BY_CARD_TYPE: dict[str, str] = {
    # ...existing...
    "create_reminder": "I've prepared a reminder for you to review and approve.",
}
```

#### Step 9 — The migration (read this one carefully)

Two tables gate your new value with a SQL `CHECK` constraint: `approval_cards.card_type` (`migrations/0008_approval_cards.sql`) and `dictation_intents.intent_type` (`migrations/0007_dictation_intents.sql`). These constraints are the enforcement plane — they're *why* an unknown card type can't be smuggled into the database — so widening them is deliberately not a one-liner.

**SQLite cannot `ALTER` a `CHECK` constraint.** The only way to change one is the official [table-redefinition procedure](https://www.sqlite.org/lang_altertable.html#otheralter): create a new table with the wider constraint, copy every row, drop the old table, rename the new one, and **re-create the indexes and triggers** (dropping the old table drops them too). Add a **new** migration file — never edit `0007`/`0008`, which have already run on users' machines. The runner (`engine/storage/sqlite_migrations_runner.py`) wraps each file in one transaction, so **don't** add your own `BEGIN`/`COMMIT`.

```sql
-- migrations/0010_add_create_reminder.sql
-- Adds 'create_reminder' to approval_cards.card_type and
-- dictation_intents.intent_type. SQLite can't ALTER a CHECK, so each table
-- is rebuilt (the official redefinition), rows are copied, and every index
-- and trigger is re-created. Do NOT add BEGIN/COMMIT — the runner wraps this.

----------------------------------------------------------------------
-- approval_cards: widen card_type
----------------------------------------------------------------------
CREATE TABLE approval_cards_new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id    TEXT REFERENCES meetings(id),
    source        TEXT NOT NULL CHECK (source IN ('extraction', 'dictation')),
    source_row_id INTEGER NOT NULL,
    card_type     TEXT NOT NULL CHECK (card_type IN
                      ('create_event', 'find_slot', 'upsert_contact',
                       'write_note', 'draft_email', 'create_reminder')),  -- ← added
    payload_json  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                      ('pending', 'approved', 'executing', 'executed',
                       'failed', 'dismissed')),
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    executed_at   TEXT,
    result_json   TEXT,
    error         TEXT
);

INSERT INTO approval_cards_new SELECT * FROM approval_cards;
DROP TABLE approval_cards;
ALTER TABLE approval_cards_new RENAME TO approval_cards;

-- Re-create the indexes and ALL SEVEN triggers verbatim from
-- migrations/0008_approval_cards.sql — they are UNCHANGED, so copy them
-- exactly (do not paraphrase — these enforce approval-before-execute):
--   idx_approval_cards_status, idx_approval_cards_source, idx_approval_cards_meeting_id
--   approval_cards_insert_must_be_pending
--   approval_cards_enforce_status_transitions
--   approval_cards_decision_requires_decided_at
--   approval_cards_outcome_requires_executed_at
--   approval_cards_provenance_immutable
--   approval_cards_payload_locked_after_decision
--   approval_cards_block_delete

----------------------------------------------------------------------
-- dictation_intents: widen intent_type (same procedure; copy the two
-- append-only triggers verbatim from migrations/0007_dictation_intents.sql)
----------------------------------------------------------------------
-- CREATE TABLE dictation_intents_new ( ... intent_type CHECK ( ... , 'create_reminder') ... );
-- INSERT INTO dictation_intents_new SELECT * FROM dictation_intents;
-- DROP TABLE dictation_intents; ALTER TABLE dictation_intents_new RENAME TO dictation_intents;
-- ... re-create idx_dictation_intents_ts + the block_update / block_delete triggers ...
```

Copy the trigger and index bodies **exactly** from the original migrations — they don't change, and this is the one place where a paraphrase could quietly disarm a security control. If you're only adding an extraction-sourced ability (no Naomi voice path), you only need to rebuild `approval_cards`, not `dictation_intents`.

> Honest note for the maintainers: this two-table rebuild is the most involved step by far, and it's inherent to using baked-in `CHECK` constraints as the enforcement plane. It's a fair place to ask whether a future refactor wants a lookup table or an app-level enum instead. Until then, the rebuild is the correct, safe path.

#### Step 10 — Tests (with teeth) and the count guards

Your tool isn't done until it's tested adversarially. Add a file named for the behaviour, e.g. `tests/test_agents__reminder_tool_edges.py`. Model it on the existing tool tests — `test_agents__tool_registry_draft_only_and_dry_run.py` and `test_agents__contacts_and_calendar_tool_edges.py` are the closest. Cover at least:

- **`dry_run` is byte-exact** — assert the exact preview tuple for a reminder with and without a due hint. This is what the user sees; pin it.
- **`execute` is local-only** — assert `data_sent_off_machine == ""`, and that the note actually lands in `Inbox/` with the right frontmatter.
- **Never overwrites** — two reminders with the same text produce two files (collision suffixing), never one clobbered.
- **Mismatched params are refused** — hand your tool a `ContactsUpsertParams` and assert it raises `ToolExecutionError`, never guesses.
- **Boundary cases** — empty text is rejected by the model; a 501-char text is rejected; a due_hint at exactly 200 chars is accepted and at 201 rejected.
- **The mapper stays deterministic** — a `CreateReminderCardPayload` maps to concrete params with `is_deterministic` true; it never routes to the LLM.
- **Round-trips through approval** — build a `pending` card, approve it, execute it via `execute_approved_card`, and assert exactly one `audit_log` row was written and the card ended `executed`.

Write tests that would **fail if the code were wrong**. A test asserting `dry_run` "returns a tuple" proves nothing; one asserting it returns *exactly* `("Reminder: Call the dentist", "Due: tomorrow", "Saved to Inbox/ (local only)")` has teeth.

**The count guards will go red — that's by design.** The suite has deliberate "adding a capability must be loud" assertions, e.g. in `test_agents__tool_registry_draft_only_and_dry_run.py`:

```python
def test_registry_exposes_exactly_the_five_card_types(tmp_path: Path) -> None:
    registry = build_default_tool_registry(tmp_path)
    assert registry.registered_card_types() == frozenset(CardType)
    assert len(frozenset(CardType)) == 5  # ← this line now fails: it's a tripwire
```

When you add a card type, this test *should* fail — it's the tripwire telling you a new capability entered the system. Update the count to `6` (and rename the test), and add your reminder tool to the relevant parametrized dry-run cases. That red is the safety net doing its job, not a bug.

Run the full [gate](#running-the-gate), get it green, and you've shipped a new ability. That's genuinely all there is to it.

### What changes for a tool that talks to the internet

A weather lookup, a web search, a Spotify command — same ten steps, with one difference: `execute` calls a provider, so a few extra rules apply. Rather than hand you fake gateway code, here's the honest shape, with the real files to mirror:

- **Egress goes through a gateway that respects the kill-switch.** `engine/google/google_api_gateway.py` is the pattern: a thin module that owns the outbound call and refuses when the kill-switch is engaged (fail closed on egress). A new external capability gets its own small gateway module under `engine/`, not a raw `requests.get` inside the tool.
- **State exactly what leaves the box.** Set `data_sent_off_machine` to a plain-English account of the fields and destination — it goes verbatim into the audit log. "the search query text to the DuckDuckGo API" is honest; leaving it blank when data left the box is not.
- **Send the minimum.** Treat every field as untrusted, send only what the task needs, and never include vault content the user didn't ask you to.
- **Anything outbound-to-a-person is draft-only.** Posting to Slack, sending a text, emailing — draft it or stage it for the user to confirm. The Gmail tool is the precedent and the line: Omni prepares, the user dispatches.
- **A new provider means a key**, and keys are DPAPI-only, held by the engine, entered at onboarding. Never read a key from a file or env var you added; wire it through the existing key store.

If an ability can't fit those rules, it's a great **[proposal](#branch-commit-and-pr-flow)** — open a `new ability` issue and let's talk about the safest shape before you build.

---

## Non-negotiables

A tool that does any of these will be declined — not because the idea is bad, but because it breaks the promise Omni makes to its users. We'll always try to help you find a version that fits.

- **Executes without approval.** Every action is a card the user approves. No auto-run, no "just this once", no instant-execute you didn't route through the whitelist the user set.
- **Sends on the user's behalf.** Draft-only. If it leaves as a message from the user, it must be staged for them to send.
- **Phones home.** Any telemetry, analytics, crash-reporting, or "anonymous" beacon. Zero means zero.
- **Exfiltrates.** Sends vault content, transcripts, or keys anywhere the user didn't explicitly configure, or sends more than the task needs.
- **Handles keys carelessly.** Keys in files, logs, env vars, the UI process, or plaintext on disk. DPAPI, engine-only, or it doesn't ship.
- **Weakens a control to pass a test.** Widening a `CHECK`, disarming a trigger, or skipping a guard to get green. Fix the code or the design instead.
- **Oversized or vaguely named files.** Over 300 lines, or a `utils.py`/`helpers.py` junk drawer. Split by responsibility; name it for what it holds.

---

## Branch, commit, and PR flow

- **Branch off `main`.** Use a descriptive name — `feature/reminder-tool`, `fix/mapper-none-due-hint`.
- **Keep `main` shippable.** Every commit builds, passes the full suite, and clears the gates. Small, coherent commits beat one giant drop.
- **No dead code.** If your change supersedes something, delete the old version in the same change — git is the safety net, not a graveyard of `_old` files.
- **Write commit messages that say what changed and why.** The "why" is the valuable half.
- **Open a PR against `main`** using the [pull-request template](.github/PULL_REQUEST_TEMPLATE.md). Fill in the checklist honestly — a reviewer will check the real artifacts, not the ticked boxes.
- **CI must be green.** PRs are reviewed once the gate passes (ruff, mypy, pytest, and the UI checks if you touched `apps/ui/`). A red PR isn't ready for review yet — that's fine, mark it a draft.

Not sure where to start? The [good-first-abilities list](docs/ability-ideas.md) is a curated menu of tools the community could add, each tagged with its difficulty and the one invariant to watch. Opening a **[new ability](.github/ISSUE_TEMPLATE/new_ability.yml)** issue to sketch the idea first is always welcome — it's the best way to make sure the shape is right before you build.

---

## License and sign-off

Omni is [MIT-licensed](LICENSE). **By contributing, you agree that your contributions are licensed under the MIT License** and that you have the right to submit them. No separate CLA — the MIT terms are the whole agreement. Please keep any code you contribute free of third-party material you can't license this way.

Be excellent to each other — see the [Code of Conduct](CODE_OF_CONDUCT.md). Found a security issue? Don't open a public issue; follow [SECURITY.md](SECURITY.md) instead.

Welcome aboard. Go teach Naomi something new.
