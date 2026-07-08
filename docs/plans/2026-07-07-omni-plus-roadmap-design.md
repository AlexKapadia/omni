# Omni+ Feature Roadmap — Refined Design

**Date:** 2026-07-07  
**Project:** Omni (Fork — bhaskaraanjana/omni)  
**Status:** Approved for phased implementation

## Architecture Correction

The original roadmap assumes Rust/Tauri owns STT, detection, and AI. **Omni's actual split:**

| Layer | Path | Responsibility |
|-------|------|----------------|
| Tauri shell | `apps/ui/src-tauri/` | Tray, hotkeys, text injection, engine process supervisor |
| React UI | `apps/ui/src/` | WebSocket client, live screens, settings |
| Python engine | `engine/` | STT, audio, detection, ask, Naomi, Google, vault, router |

**Do not duplicate engine logic in Rust.** Extend the Python engine and wire the UI.

### Phase 0 Reframe

Skip `tokio::sync::broadcast` in Rust. Python already has `engine/protocol/event_broadcast_hub.py` fanning WS events to all clients. Phase 0 = ensure UI reacts to engine events (auto-start, live captions) without new IPC.

---

## Gap Analysis by Phase

### Phase 1 — Automation & Triggers

| Item | Status | Actual location |
|------|--------|-----------------|
| WASAPI loopback + mic detection | **Exists** | `engine/audio/`, `engine/detect/sustained_loopback_vad_trigger.py` |
| Window/app tracking | **Exists** | `engine/detect/meeting_process_watcher.py`, `windows_desktop_snapshot_via_ctypes.py` |
| Auto-start rules engine | **Exists** | `engine/detect/auto_start_rules_engine.py` |
| Auto-start UI execution | **Missing** | UI shows toast only; never fires `capture.start` on `auto_start: true` |
| Auto-start settings persistence | **Missing** | `auto_start_sources` not in `app_settings` |
| Google OAuth / calendar tools | **Partial** | `engine/google/` — no calendar poll for pre-load |
| Silence auto-stop | **Exists** | `engine/stt/silence_auto_stop_monitor.py` via `OMNI_AUTOSTOP_SILENCE_S` |
| Silence timeout in settings UI | **Missing** | Env-only today |

### Phase 2 — Live Features

| Item | Status | Actual location |
|------|--------|-----------------|
| Live captions | **Exists** | `transcript.partial/final` → `transcript-stream.tsx` |
| Live captions overlay (always-on-top) | **Missing** | New Tauri window |
| Live translation | **Missing** | New engine module |
| Rolling summaries | **Missing** | New engine module + UI panel |
| Proactive vault suggestions | **Partial** | `live_answers_spotter.py` — extend to 30s RAG poll |

### Phase 3 — Cross-Platform

| Item | Status | Notes |
|------|--------|-------|
| macOS CoreAudio loopback | **Missing** | Abstract `engine/audio/` behind `sys_platform` |
| Linux PipeWire/Pulse | **Missing** | Same abstraction |
| CI multi-target builds | **Partial** | Extend `.github/workflows/` |

### Phase 4 — Advanced Outputs

| Item | Status | Notes |
|------|--------|-------|
| Structured meeting board | **Partial** | `engine/enhance/meeting_extraction_pipeline.py` |
| PDF/DOCX export | **Missing** | Python-side export preferred |
| File import (MP3/MP4) | **Missing** | ffmpeg + existing STT pipeline |
| SRT/VTT export | **Missing** | From transcript store |

### Phase 5 — UI/UX

| Item | Status | Notes |
|------|--------|-------|
| In-app rough notes | **Partial** | `notepad-store.ts` exists |
| Edit transcript segments | **Missing** | UI + engine command |

### Phase 6 — Advanced AI

| Item | Status | Notes |
|------|--------|-------|
| Echo cancellation | **Missing** | `engine/audio/` processor |
| Multi-language summaries | **Partial** | Router prompt extension |
| Custom summary templates | **Exists** | `engine/enhance/note_templates.py` |
| Background retranscription | **Partial** | `keep_audio` + re-run STT |

### Phase 7 — Developer Mode

| Item | Status | Notes |
|------|--------|-------|
| CLI headless mode | **Missing** | `python -m engine.server` exists; add `omni-cli` |
| BYO-LLM providers | **Partial** | Groq/Gemini/Anthropic in `engine/router/` |

---

## Implementation Order

1. **Phase 0/1** — Auto-start UI wiring + detection settings persistence
2. **Phase 1** — Calendar poll, silence timeout settings, tray capture
3. **Phase 2.1** — Live captions overlay window
4. **Phase 2.3–2.4** — Rolling summaries + proactive RAG sidebar
5. **Phase 4.1** — Structured meeting board UI
6. **Phase 4.2–4.4** — Export formats
7. **Phase 5** — Rough notes fusion + transcript editing
8. **Phase 6** — AEC, retranscription
9. **Phase 3** — Cross-platform (after Windows stable)
10. **Phase 7** — CLI + provider expansion

---

## Testing Strategy

- **Python:** `uv run pytest tests/` — every engine change
- **UI:** `pnpm test` in `apps/ui/` — vitest for stores and wiring
- **Integration:** existing e2e harness in `apps/ui/e2e/`
- Each phase completes only when its tests pass
