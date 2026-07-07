# Progress — Live E2E + Product-Media Lane

**North Star:** A live, browser-driven Playwright E2E suite that drives the REAL
running Omni app (React frontend + real Python engine over the real WebSocket) —
exercising every interactive element across every screen — plus REAL product-media
(screenshots + a genuinely RECORDED video → mp4/gif) captured from the running app
in a real (health-gated) success state. Never mock mode. (§4.9, §4.9.8)

**Branch / worktree:** `feature/e2e-and-media` at `C:\dev\Omni-e2e`.

## Resume here
Harness proven end-to-end. NEXT: finish Playwright config + fixtures + specs, run
green headed, capture media, self-verify by viewing images.

## What is shimmed (honest disclosure — captions must match)
Plain Chromium lacks Tauri-native APIs. We stub ONLY OS-native calls; every
data-bearing call flows through the REAL engine over the real WS:
- `window.__omniPickDirectory` → returns the real tmp vault path (the file-dialog
  seam the app already exposes in `pick-vault-directory.ts`). Replaces the native
  folder picker only.
- (pill window only) `@tauri-apps/api` window/core/event stubs — the main shell
  never imports Tauri, so the shim there is just the picker seam.
Everything else (setup.status, ask.query, meetings.list/get, settings.*, ledger,
capture.*) is the REAL engine.

## Proven (smoke, 2026-07-07)
- Real engine boots via `python -m engine.server` (.venv at C:\dev\Omni\.venv). ✅
  Startup ~90s (torch/nemo import); STT preload fails harmlessly on empty model
  placeholders (stt_ready=false) — server serves fine.
- `GET /health` → 200. ✅
- Seed script (`apps/ui/e2e/harness/seed_engine.py`): applies real migrations,
  indexes fixture vault (5 notes, 16 chunks), sets onboarding_complete, seeds 3
  synthetic finalized meetings + transcripts. ✅
- **REAL `ask.query`** → `ask.answer no_answer=false citations=1 retrieval_ms=4
  synthesis_ms=6949` (real Gemini synthesis). ✅ ← the health-gate signal.

## Key facts (runbook)
- ask_synthesis routes to Gemini/Anthropic (NOT Groq); GEMINI_API_KEY required.
- Keys read from engine PROCESS ENV via key-store env fallback (no DPAPI write).
- Port pinned 8765 (UI hardcodes ws://127.0.0.1:8765/ws) — kill stale first.
- setup.status complete needs: groq+gemini keys (env), vault (OMNI_VAULT_DIR),
  onboarding_complete=true (seeded), and two model files present (empty
  placeholders in OMNI_MODELS_DIR satisfy the .is_file() check).
- Env for engine: OMNI_ENGINE_PORT, OMNI_DB_PATH, OMNI_VAULT_DIR, OMNI_MODELS_DIR,
  GEMINI_API_KEY, GROQ_API_KEY, PYTHONUTF8=1.

## Plan / checklist
- [x] Explore engine boot + seed + ask runbook
- [x] Fixture vault (synthetic, no PII) + seed script + ask probe
- [x] Smoke: real boot + health + real ask.query
- [ ] pnpm install in worktree + playwright install chromium
- [ ] Playwright config + global-setup (boot engine, seed, health-gate real ask) + teardown
- [ ] Tauri shim init-script
- [ ] E2E specs: onboarding, library, ask, settings, live, naomi, pill
- [ ] Run suite green headed (report count)
- [ ] Media capture (recordVideo + screenshots) + ffmpeg mp4/gif → media/
- [ ] Self-verify: VIEW every PNG + video frames vs design brief
- [ ] ruff/typecheck clean on harness code; commit + push

## Agent ledger
- Explore "engine boot runbook" — returned, integrated. ✅
- Explore "meetings DB seed schema" — returned, integrated (fixed seed SQL). ✅
