# Overnight blocker-fix run — 2026-07-17

**North Star:** every quality gate green so the app builds, packages, and runs as a finished product. Fixes executed by `grok` CLI (grok-4.5, reasoning-effort high), verified by the orchestrator re-running each gate.

**Branch:** `feature/ui-rehaul-v2`. WIP safety commit made before any automated edits.

## Gate state at start of run

| Gate | Command | State |
| --- | --- | --- |
| Engine tests | `uv run pytest` | GREEN (~2300 tests, 1 skip) |
| UI tests | `npm run test` (vitest) | GREEN (1015 tests / 107 files) |
| Rust | `cargo check` | GREEN |
| UI typecheck / build | `npx tsc --noEmit` | **RED — 44 errors** (blocks `npm run build`) |
| Engine lint | `uv run ruff check .` | **RED — 103 errors** (52 auto-fixable) |
| Engine types | `uv run mypy` | **RED — 90 errors in 43 files** |

Full error inventories: `docs/progress/gate-tsc-errors.txt`, `gate-ruff-errors.txt`, `gate-mypy-errors.txt`.

## Issue list / checklist

### Batch A — UI TypeScript errors (44) — BLOCKER: breaks `npm run build`
Status: `TODO`
- `exactOptionalPropertyTypes` violations: lucide icon components passed where `{size?: number}` expected (settings-screen.tsx ×6, dictation-history-screen.tsx ×2, toggle-chip test ×1); style-prop TS2375 in coachmark.tsx, tooltip.tsx, meeting-detected-toast.tsx ×2; payload objects with `| undefined` members (meeting-board-panel.tsx ×2, capture-protocol.ts, library-meeting-detail-pane.tsx)
- Readonly-array mutation: meetings-live-repository.ts `.push` on readonly arrays ×2
- WebSocket factory type mismatch: captions-engine-bridge.ts, meeting-toast-engine-bridge.ts (also `.message` property access on wrong union arm)
- TS2556 spread-argument errors in test files (App__boot-refreshes-devices, wire-meeting-toast-desktop, meeting-toast-view, dictation-pill-view)
- Test fixture shape drift (missing new EngineSettings/onboarding fields): wire-auto-summary, wire-captions-overlay, onboarding-wizard tests ×5, summary-model-section test ×2, transcription-backend-section test
- Unused declarations TS6133: step-features-tour `onContinue`, ask-screen `provider`, home-screen `HelpCircle`/`filterMeetings`, onboarding-wizard `vaultConfigured`
- nav-rail.tsx TS2367 unintentional comparison

### Batch B — engine ruff (103) — MAJOR: CI lint gate red
Status: `TODO` — run `uv run ruff check . --fix`, then hand-fix the remainder (unused imports, import organization, etc.)

### Batch C — engine mypy (90 in 43 files) — MAJOR: CI type gate red
Status: `TODO` — missing annotations in tests, `Row | None` indexing, protocol re-export gaps (`engine/protocol` not exporting MeetingTextReplacePayload etc.), fake-router protocol mismatches, dict invariance at meeting_command_dispatcher.py:398.

### Batch D — product-level blockers (from deep scan)
Status: `IN-PROGRESS` — explore agent scanning wiring of meeting-toast feature, packaging readiness, unwired UI, dispatcher gaps. Items appended when it returns.

## Agent ledger
| Agent | Brief | Status |
| --- | --- | --- |
| explore-scan | product-level blocker scan | running |
| grok batch A | fix 44 tsc errors | pending |
| grok batch B | fix ruff | pending |
| grok batch C | fix mypy | pending |
| grok batch D | fix product blockers | pending |

## Resume here
If picking this up cold: check gate state table vs reality (`npx tsc --noEmit` in apps/ui; `uv run ruff check .`; `uv run mypy`), then continue with the first non-green batch. Verify after every batch: the fixing agent's word is not evidence.

## Constraints binding on all fix agents
- Never weaken a gate to pass it (no ts-ignore/eslint-disable/type: ignore/noqa unless genuinely unavoidable and justified inline).
- No behavior changes while fixing types/lint; tests must stay green.
- Do not touch `instagram_not_following_back.csv`, `unfollow_*.txt`, `skipped_not_person.txt` (unrelated user files, untracked on purpose).
