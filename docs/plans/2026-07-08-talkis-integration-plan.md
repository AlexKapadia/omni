# Talkis → Omni+ Integration Plan

**Date:** 2026-07-08  
**Author:** Lead Product Architect (planning pass)  
**Talkis source:** [SerTimBerrners-Lee/talkis](https://github.com/SerTimBerrners-Lee/talkis) (v0.3.8, AGPL-3.0)  
**Omni baseline:** `docs/plans/2026-07-07-omni-plus-roadmap-design.md` + full test suites green (2026-07-08)

---

## Executive summary

Omni already implements **most of the Talkis prompt’s headline features** on Windows: global dictation, floating pill, dual-track meeting capture, file import, LLM cleanup (BYOK), speaker labeling, and a searchable meeting library. **Do not re-port those.**

The real opportunity is to cherry-pick Talkis capabilities that make Omni indispensable **between meetings** and on **more platforms**, without duplicating engine logic in Rust or breaking Omni’s Python-engine architecture.

**Integration strategy:** clean-room reimplementation of *patterns* (not AGPL code copy), extend `engine/` + wire UI, keep Rust shell limited to tray/hotkeys/paste/overlays.

---

## License blocker (read first)

| Repo | License |
|------|---------|
| Omni | **MIT** |
| Talkis | **AGPL-3.0-or-later** |

**We cannot copy Talkis source into Omni** without relicensing Omni to AGPL (or obtaining a separate license from Talkis authors). This plan treats Talkis as an **architecture reference** and specifies **what to build**, not what to paste.

Acceptable approaches:
- Study Talkis behavior and reimplement in Omni’s stack
- Vendor Talkis **binaries** as optional sidecars with clear AGPL attribution + source offer (if we ship their binaries)
- Negotiate dual-license with Talkis maintainers for specific modules

---

## Architecture constraint (non-negotiable)

| Layer | Omni today | Talkis today | Integration rule |
|-------|------------|--------------|------------------|
| Tauri shell | `apps/ui/src-tauri/` | All-in-one | **Extend shell only** for paste, windows, hotkeys |
| React UI | `apps/ui/src/` | `src/` | Merge UX patterns into existing screens |
| Engine | `engine/` (Python) | Rust `src-tauri/src/` | **All STT/AI/audio logic stays in Python** unless we deliberately adopt a Rust sidecar with a thin supervisor |

Use existing `EventBroadcastHub` → WebSocket. **Do not** add a Rust event bus duplicating Python events.

---

## Feature matrix: SKIP vs INTEGRATE

Legend: ✅ Done in Omni · 🔶 Partial · ❌ Not built · ⏭ Skip (already sufficient)

| # | Talkis prompt feature | Omni status | Verdict |
|---|----------------------|-------------|---------|
| 1 | System-wide dictation | ✅ F9 hold, inject/note/command (`dictation_session_service.py`, `dictation_pill_window.rs`) | **⏭ Skip core** · Enhance: locked recording, paste reliability |
| 2 | Floating widget | ✅ Dictation pill + captions overlay + tray | **⏭ Skip second widget** · Enhance pill UX (waveform, call shortcut) |
| 3 | Transcription freedom (local / cloud / BYOK) | ✅ Parakeet + Whisper + BYOK STT; Settings accuracy tiers | **Done** — live capture Parakeet-first |
| 4 | File transcription | ✅ `import.media` + library drag-drop | **⏭ Skip basic flow** · **INTEGRATE** speakers mode + large-file chunking |
| 5 | Call recording (dual track) | ✅ Windows WASAPI mic+loopback in meetings | **⏭ Skip Windows meeting capture** · **INTEGRATE** quick-call widget mode + macOS/Linux backends |
| 6 | Speaker diarization | 🔶 Live loopback clustering + enrollment | **⏭ Skip live path** · **INTEGRATE** offline file diarization |
| 7 | AI text cleanup + style presets | ✅ Classic / business / tech in Settings | **Done** |
| 8 | Local history + search | ✅ Dictation history screen + SQL search | **Done** |
| 9 | Cross-platform | ✅ Tauri bundles + sounddevice backends | **Partial** — loopback setup per platform |

### Talkis extras not in the original prompt (still worth porting)

| Feature | Omni | Verdict |
|---------|------|---------|
| Live partial dictation in UI | ✅ `dictation.partial` → pill | ⏭ Skip |
| Selection translation hotkey | ❌ | **INTEGRATE** (Phase 4) |
| DevChat / semantic search over past dictations | ❌ (Ask/RAG is vault+meetings) | **INTEGRATE** (Phase 5) |
| Talkis Cloud proxy (no API key) | ❌ | **OPTIONAL** — privacy tension; defer unless product wants hosted tier |
| Bundled local LLM (`talkis-llm`) | ❌ (Ollama/LM Studio BYOK) | **LOW** — Ollama path exists |
| Locked recording FSM (re-press to lock) | ❌ | **INTEGRATE** (Phase 1 polish) |
| STT model picker (Whisper variants, Qwen, Moonshine) | ❌ | **INTEGRATE** (Phase 2) |

---

## Phased integration plan

### Phase 0 — Discovery & boundaries (1 week) ✅ this document

**Deliverables:**
- Gap matrix (above)
- License decision recorded
- Talkis clone at `C:\DEV\talkis` for reference

**Exit criteria:** No duplicate work on dictation core, file import, or meeting capture.

---

### Phase 1 — Dictation polish (high impact, low risk)

**Goal:** Make existing dictation feel as smooth as Talkis without new subsystems.

| Item | Talkis reference | Omni implementation |
|------|------------------|---------------------|
| Locked recording | `hotkeyFsm.ts` | Extend `dictation-pill-state.ts` + `dictation_hotkey_accelerator.rs`: re-press hotkey while holding → lock until second release |
| Paste reliability | `paste.rs` (Win enigo) | Harden `dictation_text_injection.rs`: focus restore, retry, terminal detection (optional) |
| Waveform in pill | `Waveform.tsx` | Reuse design-system meter in `dictation-pill-view.tsx` (spec in `design-brief.md`) |
| Dictation history stub | `history_storage.rs` | New SQLite table `dictation_entries` + `dictation.history.list` command; pill “recent” link |

**Skip:** New widget window, new STT stack, cloud proxy.

**Files to touch:**
- `apps/ui/src/pill/dictation-pill-state.ts`
- `apps/ui/src-tauri/src/dictation_hotkey_accelerator.rs`
- `engine/dictation/dictation_history_repository.py` (new)
- `migrations/0011_dictation_history.sql` (new)

**Windows test checklist:**
1. Hold F9 → speak → release → text in Notepad
2. Hold F9 → re-press F9 → release hotkey → still recording → release again → stops
3. Note mode → entry appears in dictation history + vault Inbox
4. Inject failure shows honest error in pill

---

### Phase 2 — Pluggable STT backends (highest strategic value)

**Goal:** Users choose local Parakeet (default), Whisper variant, or BYOK cloud STT — without removing offline default.

**Talkis pattern:** `talkis-stt` sidecar (`transcribe-cpp`) + `ai/routing.rs` endpoint normalization.

**Omni adaptation (Python-first):**

```
engine/stt/
  stt_backend_protocol.py      # interface: transcribe_file, transcribe_stream
  parakeet_backend.py          # existing, wrapped
  openai_compatible_stt.py     # BYOK: /v1/audio/transcriptions
  whisper_backend.py           # optional: faster-whisper or whisper.cpp subprocess
  stt_backend_registry.py      # settings-driven factory
```

| Mode | Default | Privacy |
|------|---------|---------|
| Local Parakeet | ✅ default | Fully offline |
| Local Whisper | opt-in | Fully offline |
| BYOK OpenAI-compatible | opt-in | User’s key, user’s vendor |
| Talkis Cloud | **deferred** | Requires hosted service + AGPL/vendor review |

**UI:** Settings → Transcription → engine picker + model download (extend existing `models.download` flow).

**Skip:** Re-implementing Parakeet; moving STT to Rust.

**Files to touch:**
- `engine/stt/stt_backend_registry.py` (new)
- `engine/settings/app_settings_repository.py` — `stt_engine`, `stt_model_id`
- `apps/ui/src/components/settings/transcription-backend-section.tsx` (new)
- Wire `dictation_session_service.py`, `offline_audio_transcriber.py`, `live_capture_service.py` through registry

**Windows test checklist:**
1. Default Parakeet dictation unchanged
2. Switch to Whisper tiny → dictation still works
3. BYOK OpenAI STT → dictation uses cloud (setting warns)
4. Meeting capture still works on each backend
5. `import.media` uses selected backend

---

### Phase 3 — File transcription upgrades

**Goal:** Close gap vs Talkis file tab — **speakers mode** and large files — without replacing library import.

| Item | Talkis | Omni plan |
|------|--------|-----------|
| Drag-drop on widget | Widget surface | **Optional:** also accept drop on pill (low priority; library drop exists) |
| Speakers / diarization | `talkis-diarize` sherpa-onnx | New `engine/stt/file_diarization_service.py` — evaluate **pyannote** or vendor **sherpa-onnx** as optional binary (AGPL note if shipping Talkis binary) |
| Chunked cloud upload | 25 MB chunks | Only if BYOK STT selected; `media_import_service.py` chunking |
| Progress events | `file-transcription-progress` | Extend `import.media` with progress WS events |

**Skip:** New file entity type — imports remain **meetings** in SQLite.

**Import UX:** Library import dialog → checkbox **“Identify speakers”** (off by default for speed).

**Windows test checklist:**
1. Import 60 min WAV → transcript meeting created
2. Import with speakers → segments have Speaker 1/2 labels
3. Import 2 GB mp4 → progress bar, no OOM
4. Existing library search/export unchanged

---

### Phase 4 — Dictation cleanup styles + translation

**Goal:** Talkis-style finished text, not raw transcript.

| Item | Talkis | Omni plan |
|------|--------|-----------|
| Style presets | `transcription-prompts/` JSON layers | Port **structure** (not AGPL text verbatim): `engine/dictation/cleanup_styles/` + setting `dictation_cleanup_style`: classic \| business \| tech |
| Faithfulness guard | N/A | **Keep** Omni guard — styles must not increase unfaithful rewrites |
| Selection translation | `selectionTranslation.ts` | New hotkey → read selection → translate → overlay or replace; `engine/translate/selection_translate_service.py` |

**Skip:** Replacing `dictation_cleanup.py` router; meeting `note_templates` stay separate.

**Windows test checklist:**
1. Classic vs business cleanup on same utterance → measurable tone difference, raw retained
2. Faithfulness guard still blocks hallucinated cleanup
3. Select text in browser → translation hotkey → overlay shows translation

---

### Phase 5 — Dictation history & DevChat

**Goal:** In-app searchable history for **all dictation modes**, not only vault Inbox.

| Item | Talkis | Omni plan |
|------|--------|-----------|
| History storage | JSON files | SQLite `dictation_entries` (Phase 1) + optional audio retention |
| Search | Keyword + embeddings | Keyword in SQL; optional `sqlite-vec` embeddings reusing ask index infra |
| DevChat over history | `DevChatTab.tsx` | New **Dictation** tab or extend Ask screen with scope `dictation_only` |

**Skip:** Replacing meeting library; Obsidian vault remains source of truth for note mode.

---

### Phase 6 — Cross-platform capture & paste

**Goal:** Own Windows (done); port Talkis **platform-specific shell** patterns for macOS/Linux.

| Platform | Port from Talkis (reference) | Omni target |
|----------|------------------------------|-------------|
| macOS paste | CGEvent Cmd+V (`paste.rs`) | `dictation_text_injection.rs` macOS module |
| Linux paste | XTest + xclip (`paste.rs`) | Linux module + terminal-aware shortcuts |
| macOS system audio | Core Audio tap (`call_capture.rs`) | `engine/audio/macos_loopback_backend.py` (new) |
| Linux system audio | PipeWire (`call_capture.rs`) | `engine/audio/pipewire_capture_backend.py` (new) |

**Skip:** Rebuilding meeting intelligence UI per platform.

**Prerequisite:** Hardware CI runners (roadmap Phase 3).

---

## What we explicitly defer

| Item | Why |
|------|-----|
| Talkis Cloud proxy | Conflicts with privacy-first default; AGPL + hosted ops burden |
| Second floating widget app | Pill + captions already cover use cases |
| Rust-owned STT monolith | Violates Omni architecture; duplicates Python engine |
| Full Talkis settings app | Merge into Omni Settings tabs |
| Template JSON import/export | **Done** — Settings → Templates |
| FDAF-grade AEC | Optional upgrade path exists (`stream_echo_canceller.py`) |
| Copying Talkis prompt JSON verbatim | AGPL; rewrite prompts in Omni voice |

---

## Implementation order (recommended)

```
Phase 1  Dictation polish + history table     ← start here (days)
Phase 2  Pluggable STT                        ← weeks, highest ROI
Phase 3  File diarization                     ← depends on Phase 2 optional binary
Phase 4  Cleanup styles + translation       ← parallel with Phase 3
Phase 5  History UI + DevChat scope           ← after Phase 1 table
Phase 6  macOS/Linux                          ← hardware-dependent
```

---

## Validation strategy

**Per phase:**
1. `uv run pytest tests/` — no regressions
2. `cd apps/ui && npx vitest run`
3. `cd apps/ui/src-tauri && cargo check`
4. Manual Windows script in phase section above
5. Feature flag new backends (`stt_engine != parakeet`) default off

**Regression guards:**
- Meeting capture + speaker labels (existing suites)
- Dictation faithfulness guard benchmarks (`evidence/measure/`)
- Kill switch / approval cards untouched

---

## Known limitations after integration

| Limitation | Notes |
|------------|-------|
| AGPL | Cannot ship Talkis code without license change |
| File diarization quality | pyannote/sherpa adds model size + CPU/GPU cost |
| Cloud STT | Opt-in only; breaks offline guarantee when selected |
| macOS/Linux | Phase 6; Windows remains first-class |
| Widget vs pill | No pixel-parity with Talkis orb — intentional |
| Import diarization | Slower than plain import; user opt-in |

---

## Summary for stakeholders

### Already integrated (no Talkis work needed)
Global dictation, pill overlay, captions, tray, Windows dual-stream meetings, file import, markdown/PDF export, meeting library search, BYOK LLMs, live speaker labels, dictation cleanup (single style), Naomi, calendar, vault RAG.

### To integrate from Talkis (net new)

**Status (2026-07-08):** Items 1–6 below are **implemented** unless noted.

1. ~~**Pluggable STT**~~ — **Done**
2. ~~**Offline file diarization** on import~~ — **Done**
3. ~~**Dictation cleanup style presets**~~ — **Done**
4. ~~**In-app dictation history**~~ — **Done** (keyword search; semantic search optional)
5. ~~**Locked recording**~~ — **Done** (paste hardening still optional)
6. **Selection translation hotkey** — engine exists; Rust hotkey not wired
7. **macOS/Linux** — bundles + capture backends **done**; full loopback requires user device setup

### Deferred
Talkis Cloud, AGPL code merge, duplicate widget, Rust STT rewrite.

---

## Next action

Approve **Phase 1** (dictation polish + `dictation_entries` table) or jump to **Phase 2** if STT choice is the priority. No code should land without updating this doc’s exit criteria checklist.

---

## Implementation status (2026-07-08)

**Implemented in this pass:**

| Phase | Status |
|-------|--------|
| 1 Locked recording + dictation history table | Done (`dictation-hotkey-fsm.ts`, migration `0011`, `dictation.history.list`) |
| 2 Pluggable STT | Done (Parakeet / Whisper / BYOK OpenAI-compatible + Settings UI) |
| 3 File diarization + import progress | Done (`identify_speakers`, `import.media.progress` events) |
| 4 Cleanup style presets | Done (classic / business / tech in Settings) |
| 5 Dictation history UI + Ask `dictation_only` scope | Done (Dictation nav tab, `ask.query` scope) |
| 6 macOS/Linux capture + paste | Done — `sounddevice_capture_backend.py`, release CI matrix; inject/paste polish remains |
| Template JSON import/export | Done (Settings → Templates) |

**Still manual / follow-up:**

- Selection translation hotkey (engine service exists; Rust hotkey + clipboard read not wired)
- Paste hardening retries (existing injection path unchanged)
- Pill waveform meter (design tokens exist; visual not added)
- Talkis Cloud proxy (deferred by design)
