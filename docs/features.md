# Omni features

User-visible capabilities as of 2026-07-08. Platform notes are honest — partial means available with setup or reduced fidelity.

## Meeting intelligence

| Feature | Description | Platforms |
| --- | --- | --- |
| Bot-free capture | Dual labelled streams: loopback (`them`) + mic (`me`) | Windows full · macOS/Linux partial loopback |
| On-device transcription | Silero VAD + streaming STT | All (GPU optional) |
| Live captions | Always-on-top overlay | All |
| Enhanced notes | Fuses rough notes + transcript; user text untouched | All |
| Live translation | Optional live translation stream | All |
| Rolling summary | Periodic live summary panel | All |
| Proactive vault | Suggests relevant vault snippets during meeting | All |
| Meeting board | Structured board view during live session | All |
| Speaker identity | Enroll your voice; relabel in settings | All |
| Edit transcript | Segment-level edits | All |
| Retranscribe | Background re-run with selected STT backend | All |
| Auto-start | Rules from loopback VAD, mic, window title, calendar | Windows primary |

## Library & export

| Feature | Description |
| --- | --- |
| Meeting library | Searchable list grouped by day |
| Tabbed detail | Summary · Transcript · Chat |
| Chat with meeting | `ask.query` scoped to one meeting |
| Search & replace | Transcript and summary text replace |
| Copy to clipboard | Summary, transcript, full markdown |
| Export | Markdown, PDF, DOCX, SRT, VTT, TXT |
| File import | Audio/video via ffmpeg; optional speaker identification |
| Drag-and-drop import | Native drop on library (Tauri) |

## Ask & knowledge

| Feature | Description |
| --- | --- |
| Vault RAG | BM25 + dense embeddings (`bge-small`) in sqlite-vec |
| Inline citations | Note path + line range on every claim |
| Live answers | Spotter during capture |
| Dictation-only Ask | Query past dictation entries |
| Kill switch | Halts all external model calls; local features continue |

## Dictation

| Feature | Description | Platforms |
| --- | --- | --- |
| Push-to-talk pill | Global hotkey, floating UI | All |
| Locked recording | Re-press hotkey while holding to lock until second release | All |
| Inject mode | Types into focused app | Windows |
| Note / command modes | Vault note or Naomi intent | All |
| Cleanup styles | Classic, business, tech presets | All |
| Faithfulness guard | Raw text retained; cleanup cannot silently rewrite | All |
| Dictation history | In-app searchable history screen | All |
| History search | SQL keyword search (semantic search optional future) | All |

## Transcription backends

| Tier | Engine | Use case |
| --- | --- | --- |
| Fast (default) | Parakeet-TDT on GPU/CPU | Live capture, low latency |
| Enhanced | Whisper (CUDA when available) | Import, retranscribe, accuracy |
| Cloud / BYOK | OpenAI-compatible endpoint | User-provided STT API |

Live capture remains Parakeet-first; tier picker applies to import, retranscribe, and settings-driven backend loads.

## Automation & calendar

| Feature | Description |
| --- | --- |
| Google Calendar | OAuth, upcoming events, create/find-slot tools |
| Microsoft Graph | Outlook calendar connect + poll |
| Silence auto-stop | Ends capture after configured silence |
| Detection settings | Auto-start sources and thresholds in Settings |

## Actions & Naomi

| Feature | Description |
| --- | --- |
| Approval cards | Pending → approved → executed; SQL-enforced |
| Agent tools | Calendar, contacts, vault write, Gmail **draft** |
| Naomi voice agent | Hands-free vault Q&A + action preparation |
| Instant-execute whitelist | User-opt-in only; deny by default |
| Audit ledger | Append-only log of every external call and execution |

## Privacy & security (product features)

- Local-first storage; zero telemetry
- Audio kept on-device as MP3 alongside the transcript by default (opt out to discard after transcription)
- DPAPI-encrypted keys (engine only)
- Prompt-injection defenses at model boundaries
- Managed vault regions between `<!-- omni:managed -->` markers

## CLI (headless)

`omni-cli` — `list`, `get`, `export`, `import`, `record` for scripting without the UI.

## Not yet / deferred

| Item | Notes |
| --- | --- |
| Selection translation hotkey | Engine service exists; Rust hotkey not wired |
| Talkis Cloud STT proxy | Deferred — conflicts with privacy default |
| FDAF-grade echo cancellation | Simple loopback subtraction today |
| Full macOS/Linux dictation inject | Paste paths planned |
| Semantic dictation search | Keyword search only today |

See [plans/2026-07-08-talkis-integration-plan.md](./plans/2026-07-08-talkis-integration-plan.md) and [plans/2026-07-07-omni-plus-roadmap-design.md](./plans/2026-07-07-omni-plus-roadmap-design.md) for roadmap detail.
