# Omni+ Feature Roadmap — Refined Design

**Date:** 2026-07-07 (updated 2026-07-08)  
**Project:** Omni (Fork — bhaskaraanjana/omni)  
**Status:** Windows feature set complete; Meetily Pro parity gaps closed (2026-07-08)

### Talkis integration (2026-07-08)

See **[Talkis → Omni+ Integration Plan](./2026-07-08-talkis-integration-plan.md)**. Most Talkis headline features are **already in Omni** — integration focuses on pluggable STT, file diarization, dictation styles/history, and cross-platform backends. Talkis is AGPL; clean-room reimplementation only.

### Meetily Pro parity (added 2026-07-08)

| Meetily Pro feature | Omni status |
|---------------------|-------------|
| Chat with your meetings | **Done** — Library detail → Chat tab (`ask.query` + `meeting_id`) |
| Search & replace (transcript + summary) | **Done** — Tools tab → `meeting.text.replace` |
| Copy to clipboard | **Done** — Tools tab (summary, transcript, full markdown) |
| Markdown export | **Done** — `meeting.export` format `md` + CLI |
| Tabbed meeting detail (Summary / Transcript / Chat) | **Done** — Library detail pane tabs |
| Speaker identity (settings re-enroll) | **Done** — Settings → Your voice in meetings |
| Custom template import/export (JSON) | **Done** — Settings → Templates import/export JSON |

### Still ahead of Meetily / not in Meetily

| Feature | Omni |
|---------|------|
| Naomi voice agent, approval cards, dictation pill | Omni only |
| Kill switch, instant-execute whitelist, audit ledger | Omni only |
| Live answers spotter, proactive vault, rolling summary | Omni only |
| Microsoft + Google calendar (Meetily: coming soon) | **Done** in Omni |
| Obsidian vault as source of truth | Omni core (Meetily: coming soon) |
| Pluggable transcription engines (Whisper variants, cloud STT picker) | **Done** — Settings accuracy tier; import + retranscribe honor backend |
| Windows GPU model picker / “enhanced accuracy” tier | **Done** — Fast (Parakeet GPU) / Enhanced (Whisper GPU) / Cloud presets |
| macOS capture | **Partial** — sounddevice mic + monitor loopback when available |
| macOS/Linux app bundles | **Done** — Tauri dmg/app/deb/appimage targets + release CI matrix |

## Architecture Correction (read this first)

The pasted “Omni+ Feature Implementation Roadmap” assumes **Rust owns STT, detection, calendar, and AI**. **This fork does not.** Actual split:

| Layer | Path | Responsibility |
|-------|------|----------------|
| Tauri shell | `apps/ui/src-tauri/` | Tray, hotkeys, text injection, captions overlay window, engine supervisor |
| React UI | `apps/ui/src/` | WebSocket client, live screens, settings, library |
| Python engine | `engine/` | STT (Parakeet), audio (WASAPI), detection, ask/RAG, Google/Microsoft, vault, router |

**Do not duplicate engine logic in Rust.** Extend Python + wire UI. Rust IPC event bus (Phase 0) is **not needed** — use `engine/protocol/event_broadcast_hub.py` → WebSocket.

### Phase 0 reframe

| Roadmap item | Verdict | Actual |
|--------------|---------|--------|
| `tokio::sync::broadcast` in Rust | **Skip** | `EventBroadcastHub` + WS already fan out to UI |
| Prerequisite for live features | **Done** | UI listens via `live-intelligence-event-wiring.ts` |

---

## Gap Analysis (mapped to pasted roadmap)

### Phase 1 — Automation & Triggers

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| 1.1 System audio / mic activity detection | **Done** | `engine/detect/sustained_loopback_vad_trigger.py`, `microphone_in_use_detector.py` |
| 1.2 Window / app tracking | **Done** | `engine/detect/meeting_process_watcher.py`, `windows_desktop_snapshot_via_ctypes.py` |
| Auto-start rules + settings | **Done** | `auto_start_rules_engine.py`, `detection_auto_start_sources` in settings |
| Auto-start fires capture | **Done** | `auto-start-reaction.ts` → `capture.start` when `auto_start: true` |
| 1.3 Google Calendar OAuth + poll | **Done** | `engine/google/`, onboarding step 5, `calendar_poll_service.py` → `calendar.upcoming`. **Blocker:** user must supply OAuth credentials |
| Outlook / Microsoft Graph | **Done** | `engine/microsoft/`, `microsoft.connect`, dual-provider calendar poll |
| 1.4 Silence auto-stop | **Done** | `silence_auto_stop_monitor.py`, `autostop_silence_s` in settings UI |

### Phase 2 — Real-Time & Live

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| 2.1 Live captions | **Done** | `transcript.partial/final` → `transcript-stream.tsx` |
| Always-on-top overlay | **Done** | `captions_overlay_window.rs`, `wire-captions-overlay.ts` |
| 2.2 Live translation | **Done** | `live_translation_service.py`, `live_translation_lang` setting |
| 2.3 Rolling summaries | **Done** | `live_summary_service.py`, `live-summary-panel.tsx` |
| 2.4 Proactive vault / RAG | **Done** | `proactive_vault_poller.py`, `vault-suggestions-panel.tsx` |

### Phase 3 — Cross-Platform

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| macOS CoreAudio loopback | **Partial** — `sounddevice_capture_backend.py` (mic + PipeWire/BlackHole monitor) |
| Linux PipeWire/Pulse | **Partial** — same cross-platform backend via monitor devices |
| CI multi-target release | **Done** — `.github/workflows/release.yml` Windows + macOS + Linux matrix |

### Phase 4 — Advanced Outputs

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| 4.1 Meeting board | **Done** | `meeting-board-panel.tsx` |
| 4.2 PDF & DOCX export | **Done** | `document_export.py` full meeting (notes + transcript), library download buttons |
| 4.3 File import | **Done** | `import.media` + ffmpeg + Parakeet; Library import + drag-drop |
| 4.4 SRT/VTT/TXT export | **Done** | `meeting.export`, library detail pane |
| Drag-and-drop import | **Done** | `wire-library-drag-drop.ts` (Tauri native drop) |

### Phase 5 — UI/UX

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| 5.1 In-app rough notes | **Done** | `notepad-store.ts` |
| 5.2 Edit transcript | **Done** | `transcript.segment.update` |

### Phase 6 — Advanced AI & Performance

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| 6.1 Echo cancellation | **Partial** | Simple loopback subtraction (`stream_echo_canceller.py`). Not FDAF |
| 6.2 Multi-language summaries | **Done** | `summary_language` setting + enhanced notes prompt |
| 6.3 Custom summary templates | **Done** | `note_templates.py` |
| 6.4 Background retranscription | **Done** | `meeting.retranscribe` |

### Phase 7 — Developer & Headless

| Roadmap item | Status | Where / notes |
|--------------|--------|----------------|
| 7.1 CLI headless | **Done** | `omni-cli list|get|export|import|record` |
| 7.2 BYO-LLM | **Done** | Groq, Gemini, Anthropic, OpenAI, Ollama, OpenRouter, Azure OpenAI, LM Studio |

---

## Remaining (user / platform blockers)

1. **Google / Microsoft OAuth credentials** — user must register apps and paste keys or `.env`
2. **ffmpeg** on PATH for media import
3. **Phase 3** — macOS/Linux loopback may require BlackHole (macOS) or PipeWire monitor (Linux)
4. **Optional AEC upgrade** — `webrtc-audio-processing` if simple AEC insufficient

---

## Testing

- **Python:** `uv run pytest` (2,028+ cases)
- **UI:** `cd apps/ui && npx vitest run` (825+ cases)
- **Rust:** `cd apps/ui/src-tauri && cargo check`
