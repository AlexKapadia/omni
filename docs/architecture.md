# Omni architecture

High-level map of how the desktop app is split, how data flows, and where to extend behavior. For packaging and release mechanics see [packaging/README.md](../packaging/README.md).

## Components

```
┌──────────────────────────────── Omni.exe (Tauri 2) ────────────────────────────────┐
│  Rust shell (apps/ui/src-tauri/)                                                   │
│    • Window, tray, global hotkeys, dictation pill, captions overlay                │
│    • Engine sidecar supervisor (dev: uv · prod: frozen omni-engine.exe)           │
│    • Text injection (Windows today; macOS/Linux paste paths planned)               │
│  React UI (apps/ui/src/)                                                           │
│    • WebSocket client, screens, zustand stores — no keys, no AI                     │
└───────────────────────────────────────┬────────────────────────────────────────────┘
                                        │ ws://127.0.0.1:8765 (loopback only)
                                        ▼
┌──────────────────────────────── Python engine (engine/) ───────────────────────────┐
│  wiring/ + server.py — FastAPI, WebSocket protocol, command dispatch               │
│  audio/     — capture backends (WASAPI · sounddevice cross-platform)               │
│  stt/       — Silero VAD, Parakeet / Whisper / BYOK STT backends                   │
│  index/     — vault chunking, embeddings, sqlite-vec retrieval                     │
│  router/    — Groq / Gemini / Claude (+ BYOK providers)                            │
│  agents/    — approval tools, card executor, audit                                 │
│  dictation/ — push-to-talk sessions, cleanup, history                              │
│  enhance/   — enhanced notes, meeting finalization, export                         │
│  vault/     — markdown writers, managed regions                                    │
│  naomi/     — voice agent turn loop                                                │
│  storage/   — SQLite + migrations                                                  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## Design principles

1. **Deterministic local core** — capture, storage, approval cards, audit log, vault writes. Fail closed when ambiguous.
2. **Learned layers on top** — STT, retrieval, synthesis. Each earns its place; offline defaults remain available.
3. **Engine owns secrets** — API keys via Windows DPAPI in the engine process only. The UI never holds keys.
4. **No duplicate logic in Rust** — extend Python and wire the UI. Rust handles OS integration (hotkeys, windows, injection).
5. **Events over a single bus** — `EventBroadcastHub` fans out engine events on the WebSocket; the UI subscribes via `live-intelligence-event-wiring.ts`.

## Major data paths

### Meeting capture (live)

1. User starts capture (manual, auto-start rules, or calendar hint).
2. `audio/` opens mic + loopback streams (WASAPI on Windows; sounddevice monitor on macOS/Linux when configured).
3. `stt/` streams partial/final segments over WebSocket (`transcript.partial`, `transcript.final`).
4. Rough notes + transcript feed `enhance/` for enhanced notes after finalize.
5. Meeting row + transcript land in SQLite; vault export optional on finalize.

### Ask / RAG

1. Query hits `index/` — BM25 + dense tier (when `bge-small` weights present), fused with RRF.
2. Router synthesizes answer with citations; scope can be vault-only, meeting-only, or `dictation_only`.
3. Every external call logged in router ledger + audit.

### Dictation

1. Global hotkey FSM (`dictation-hotkey-fsm.ts` + Rust accelerator) → `dictation.start/stop`.
2. Audio → STT → cleanup style → inject into focused app (Windows) or vault note mode.
3. Entries stored in `dictation_entries` + optional vault Inbox; history screen lists/search.

### Approval actions

1. Extraction or Naomi intent creates a **pending** approval card (SQL-enforced).
2. User approves → `card_executor` maps payload → registered `AgentTool`.
3. One append-only audit row per execution; Gmail remains draft-only.

## Extension points

| Goal | Where to work |
| --- | --- |
| New agent ability | `engine/agents/*_tool.py`, migrations for `card_type` | See [CONTRIBUTING.md](../CONTRIBUTING.md) |
| New settings field | `setup-settings-payloads.ts`, engine settings repository |
| New STT backend | `engine/stt/stt_backend_registry.py`, settings loader |
| New capture backend | `engine/audio/capture_backend_factory.py` |
| New UI screen | `apps/ui/src/screens/`, protocol types in `lib/protocol.ts` |

## Cross-platform status

| Capability | Windows | macOS | Linux |
| --- | --- | --- | --- |
| App bundle (Tauri) | NSIS / MSI | DMG / `.app` | deb / AppImage |
| Mic capture | ✅ | ✅ | ✅ |
| System audio loopback | ✅ WASAPI | ⚠️ BlackHole / monitor device | ⚠️ PipeWire monitor |
| Dictation inject | ✅ | Planned | Planned |
| DPAPI key storage | ✅ | Platform keychain TBD | Platform keychain TBD |

Windows is first-class for full meeting capture; macOS and Linux ship as bundles with honest partial capture until loopback devices are configured.

## Related docs

- [features.md](./features.md) — user-visible capability list
- [plans/2026-07-07-omni-plus-roadmap-design.md](./plans/2026-07-07-omni-plus-roadmap-design.md) — phased roadmap status
- [threat-model.md](./threat-model.md) — security boundaries
