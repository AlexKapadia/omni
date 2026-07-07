"""Deterministic E2E seed: prepare a real Omni DB so the live suite exercises
the REAL engine against real, indexed data — never mock mode.

What it does (all against the real engine modules, no fakes):
  1. Applies the real migrations to the target SQLite DB (idempotent).
  2. Indexes the synthetic fixture vault into the FTS/chunk tables via the
     real VaultIndexerService, so ask.query returns real BM25 citations.
  3. Marks onboarding_complete=true through the real app-settings repository
     (append-only history preserved) so the UI boots into the main shell.
  4. Seeds a few synthetic FINALIZED meetings (no PII) so the Library screen
     and detail pane render real content.

Provider keys are NOT written here — the engine reads them from its process
environment (GROQ_API_KEY / GEMINI_API_KEY) via the key store's env fallback,
so nothing secret is ever persisted or printed by this script.

Run: python -m seed_engine --db <path> --vault <dir> --migrations <dir>
(invoked by the Playwright global setup).
"""

import argparse
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.index.vault_indexer_service import VaultIndexerService
from engine.storage.app_settings_repository import (
    SETTING_ONBOARDING_COMPLETE,
    write_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations


# --- synthetic finalized meetings (no PII; fictional companies/people) -------
def _meeting_rows() -> list[dict[str, object]]:
    base = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)
    return [
        {
            "title": "Northwind Renewal",
            "start": base,
            "duration_min": 32,
            "summary": "Renew Northwind on a 24-month term at a 12% uplift, contingent on annual billing.",
            "notes": "dana wants annual billing\nuplift ok if premium support incl\nsend order form fri",
            "enhanced": (
                "## Decision\nRenew Northwind on a **24-month term** at a 12% uplift, "
                "contingent on moving to annual billing. Premium support waived for year one.\n\n"
                "## Commitments\n- Send the revised order form by Friday.\n"
                "- Prepare the monthly to annual billing migration plan.\n\n"
                "## Risk\nProcurement freeze lifts 1 July — the signed order form must land first."
            ),
            "note_path": "Meetings/Northwind Renewal.md",
            "transcript": [
                ("them", "So on the renewal, we can live with the twelve percent uplift."),
                ("me", "Great. That's contingent on moving you to annual billing."),
                ("them", "Annual works for us — it cuts our invoice overhead anyway."),
                ("me", "Perfect. We'll waive the premium support tier for the first year."),
                ("them", "And the term would be twenty-four months?"),
                ("me", "Yes, twenty-four months. I'll send the order form by Friday."),
                ("them", "One thing — our procurement freeze lifts on the first of July."),
                ("me", "Understood, we'll make sure it's signed before your quarter closes."),
            ],
        },
        {
            "title": "Atlas Onboarding Sync",
            "start": base + timedelta(days=4, hours=3),
            "duration_min": 27,
            "summary": "Get Atlas to first production workload in 30 days; pilot runs on the EU region.",
            "notes": "kickoff 1 july, priya hosts\nEU region for data residency\n4TB migration - schedule bandwidth",
            "enhanced": (
                "## Goal\nAtlas from signed contract to first production workload within 30 days.\n\n"
                "## Decisions\n- Kick-off workshop booked for 1 July, Priya hosting.\n"
                "- Pilot runs on the EU region for data residency.\n\n"
                "## Open question\nSSO via their identity provider before go-live — Priya to confirm."
            ),
            "note_path": "Meetings/Atlas Onboarding Sync.md",
            "transcript": [
                ("me", "Let's aim for first production workload within thirty days."),
                ("them", "That works. We'll need the pilot on the EU region for data residency."),
                ("me", "Noted. We'll provision the EU environment before the kick-off."),
                ("them", "Kick-off on the first of July? I can host."),
                ("me", "Perfect. One open item is SSO before go-live."),
                ("them", "I'll confirm whether we need it wired up for the pilot."),
            ],
        },
        {
            "title": "Quarterly Planning",
            "start": base + timedelta(days=12, hours=-1),
            "duration_min": 48,
            "summary": "Renewals first, cut onboarding to 30 days, keep router model spend flat.",
            "notes": "protect the base\nNRR target 112\nrouter cost flat - route bulk to cheap provider",
            "enhanced": (
                "## Themes\n1. **Renewals first** — protect the base before new logos.\n"
                "2. **Onboarding speed** — median time-to-first-value 45 → 30 days.\n"
                "3. **Router cost discipline** — route bulk summarisation to the cheaper provider.\n\n"
                "## Targets\n- Net revenue retention: 112%.\n- Onboarding median: 30 days.\n- Model spend: flat."
            ),
            "note_path": "Meetings/Quarterly Planning.md",
            "transcript": [
                ("me", "Priority one is renewals — protect the base before chasing new logos."),
                ("them", "Agreed. Net revenue retention target of one twelve?"),
                ("me", "Yes. And onboarding median down from forty-five days to thirty."),
                ("them", "On cost, we route the bulk summarisation to the cheaper provider?"),
                ("me", "Right, that keeps model spend flat while volume grows."),
                ("them", "Let's review at the mid-quarter checkpoint on the fifteenth of August."),
            ],
        },
    ]


async def _seed_meetings(connection: object) -> int:
    """Insert synthetic finalized meetings + transcript segments, matching the
    real schema exactly (migrations 0001 + 0006): meetings has no status/summary/
    duration columns — `finalized` derives from finalized_at, `summary` from the
    first substantive line of enhanced_notes_md, and duration from the two
    timestamps. Idempotent by title so re-runs stay clean."""
    conn = connection  # aiosqlite.Connection
    seeded = 0
    for row in _meeting_rows():
        meeting_id = str(uuid.uuid4())
        start_dt = row["start"]
        ended_dt = start_dt + timedelta(minutes=int(row["duration_min"]))
        start_iso, ended_iso = start_dt.isoformat(), ended_dt.isoformat()
        # Clear any earlier seed of the same title (deterministic re-runs).
        cur = await conn.execute("SELECT id FROM meetings WHERE title = ?", (row["title"],))
        for prev in await cur.fetchall():
            pid = prev[0]
            await conn.execute("DELETE FROM transcript_segments WHERE meeting_id = ?", (pid,))
            await conn.execute("DELETE FROM meetings WHERE id = ?", (pid,))
        await cur.close()
        await conn.execute(
            "INSERT INTO meetings (id, title, started_at, ended_at, calendar_event_id,"
            " disclosed, note_path, notes_text, enhanced_notes_md, finalized_at)"
            " VALUES (?, ?, ?, ?, NULL, 1, ?, ?, ?, ?)",
            (
                meeting_id,
                row["title"],
                start_iso,
                ended_iso,
                row["note_path"],
                row["notes"],
                row["enhanced"],
                ended_iso,  # finalized_at set -> meeting.get returns finalized=true
            ),
        )
        # t_start/t_end are REAL seconds from meeting start; spread evenly.
        lines = row["transcript"]
        total_s = int(row["duration_min"]) * 60
        step = total_s / len(lines)
        for idx, (stream, text) in enumerate(lines):
            t_start = round(idx * step, 2)
            t_end = round(t_start + max(1.0, step * 0.8), 2)
            await conn.execute(
                "INSERT INTO transcript_segments (id, meeting_id, stream, text, t_start,"
                " t_end, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    meeting_id,
                    stream,  # exactly 'me' or 'them' — CHECK constraint
                    text,
                    t_start,
                    t_end,
                    (start_dt + timedelta(seconds=t_start)).isoformat(),
                ),
            )
        seeded += 1
    await conn.commit()
    return seeded


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a real Omni DB for the live E2E suite.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--migrations", required=True, type=Path)
    parser.add_argument("--skip-meetings", action="store_true")
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    await apply_migrations(args.db, args.migrations)
    connection = await open_sqlite_connection(args.db)
    try:
        indexer = VaultIndexerService(connection, args.vault)
        md_files = sorted(args.vault.glob("**/*.md"))
        report = await indexer.index_changed_files(md_files)
        await write_setting(connection, SETTING_ONBOARDING_COMPLETE, True)
        meetings = 0 if args.skip_meetings else await _seed_meetings(connection)
        # Counts only — never any secret or note content.
        print(
            f"seed: indexed_notes={report.indexed_notes} chunks={report.chunks_written} "
            f"meetings={meetings}"
        )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
