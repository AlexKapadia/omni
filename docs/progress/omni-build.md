# Omni — Build Progress Tracker (durable, resume-from-death)

> **North Star:** Production-grade, local-first, bot-free meeting intelligence engine for Windows.
> Tauri 2 + React UI, Python engine sidecar (WASAPI loopback + mic → Silero VAD → Parakeet-TDT),
> Obsidian vault as source of truth, local RAG (bge-small + sqlite-vec), approval-carded agent
> actions, tri-provider router (Groq / Gemini / optional Anthropic), NSIS installer, auto-update.
> Open source on GitHub (AlexKapadia/omni) — no secrets ever committed.

**RESUME HERE →** M0: all scaffold agents returned. Engine verified green + committed. UI TS-side
verified green; Rust side UNVERIFIED — VS2022 Build Tools C++ workload installing in background
(the old VS2019 BuildTools was a skeleton: no cl.exe/link.exe, no Windows SDK). When install
completes: `cargo check` in apps/ui/src-tauri FROM POWERSHELL (Git Bash link.exe shadows MSVC),
fix any Rust compile errors (small fix → inline; big → one Fable agent), then M0 gate: full suite
once + `pnpm tauri dev` heartbeat AC, commit gate, proceed to M1 (one Fable agent: engine
audio/ + stt/ capture pipeline).

---

## Session decisions (settled — do not re-litigate)

- **Providers: Groq + Gemini are the required pair.** Anthropic is an OPTIONAL third slot; router
  promotes Claude for synthesis/agentic work only if a key is present. Gemini function-calling
  handles agentic execution otherwise (user-approved cards gate all actions anyway).
- **Dev keys** live in `C:\dev\Omni\.env` (gitignored, `.env.example` committed). End users enter
  keys in the first-run wizard → DPAPI. As of tracker creation the user has NOT yet pasted keys —
  M0/M1 need none; check `.env` before starting M2 enhancement work.
- **Design reference:** claude.ai/design project `d160c7f8-2414-40c4-b82f-4c8375b73bd2`,
  file `Omni Design.dc.html`. Requires user `/design-login`. If unavailable, build against the
  master-prompt §8 monochrome token defaults and mark every visual decision `TODO(design)` for a
  single reconciliation pass.
- **GitHub:** authed as AlexKapadia (repo+workflow scopes). Public repo `omni`.
- **Hardware/toolchain:** RTX 4070 8GB (CUDA), Node 22 + pnpm 10, Python 3.13 system / 3.11 via uv
  for engine, Rust 1.96.1 (installed this session), ffmpeg 8. `make` NOT installed — run underlying
  commands directly (§7.1).
- **Mutation testing is never agent-initiated** (§7.7) — batched at hardening gate on CI only.
- **Keys ARE present and validated** (2026-07-06): GROQ_API_KEY + GEMINI_API_KEY in `.env`, both
  confirmed with live calls (Groq RTT 0.5s / 7ms inference; Gemini 2.5 Flash OK). User is away —
  full autonomy authorized ("run autonomously, you can walk away").
- **Repos:** old private `OMNI` renamed → `OMNI-archive` + archived (user asked delete; token lacks
  delete_repo scope — user can hard-delete later, zero data lost). Project pushed to
  **github.com/AlexKapadia/omni** (public).
- **Transcription fidelity policy (user mandate, 2026-07-06):** the raw transcript is ground truth —
  NEVER substitute words the model didn't hear; unclear audio gets conservative, clearly-bounded
  gap-fill only. Disfluency/filler removal ("ums", false starts, rambling) happens ONLY in the
  enhancement layer, never in the raw transcript. Same for typed notes: enhancement cleans, raw
  stays byte-identical.
- **Speed is a showcase feature (user mandate):** surface real-time performance in the UI — live
  per-utterance STT lag and per-call provider latency (the router ledger), visible as it happens.
- **All credentials are user-suppliable in-app (user mandate):** API keys AND Google OAuth client
  ID/secret enterable in onboarding wizard + Settings, guided so a non-developer can complete it —
  DPAPI-encrypted, plaintext never on disk. The open-source download works 100% on user-pasted keys.
- **Design access confirmed:** DesignSync reaches project `d160c7f8…` (files: `Omni Design.dc.html`,
  `ios-frame.jsx`, `support.js`). Extraction delegated to an agent → `docs/design/` + `tokens.css`.

## Milestone checklist

| Gate | Scope | Status |
|---|---|---|
| M0 Skeleton | Tauri boots to tray, sidecar spawn+handshake+restart, migrations, CI skeleton | **IN-PROGRESS** |
| M1 Ears | Dual-stream WASAPI+mic capture, VAD, streaming Parakeet, live Me/Them transcript | TODO |
| M2 Notes | Notepad, auto-stop, enhance pipeline + templates, vault writer (managed markers) | TODO |
| M3 Brain | Indexer, embeddings, Ask Omni w/ citations, live Answers panel | TODO |
| M4 Hands | Extraction, approval cards, Google OAuth, 5 tools, audit log | TODO (OAuth creds pending user) |
| M5 Voice | Dictation pill, note mode, command mode | TODO |
| M6 Detection | Calendar notify, mic-in-use, process watch, auto rules | TODO |
| M7 Ship | Onboarding wizard, model downloads, NSIS installer, auto-update, settings | TODO |
| M8 Stretch | Diarization, MCP server, weekly digest, pre-meeting brief | TODO (only after M7 green) |

## Agent ledger

| Agent | Brief | Owns | Status |
|---|---|---|---|
| design-extract v1 | tokens from Claude Design via DesignSync | docs/design/**, tokens.css | RETURNED: blocked — DesignSync not available to subagents (session-level tool). Orchestrator fetched files itself. |
| design-extract v2 | tokens from local docs/design/reference/ files | docs/design/**, tokens.css | DONE — brief + components + tokens.css committed. Flag: reference copy drift (whisper/openai placeholders) — layouts adopted, copy from real contracts. |
| memory-research | AI-facing retrieval layer research (task #10, pre-M3) | docs/research/** | DONE — 8-source library + recommendation committed. M3: structured-first routing → RRF hybrid (FTS5+sqlite-vec, k=60) → wikilink-graph expansion → chat-tier rerank. |
| engine-scaffold | M0 Python sidecar | engine/**, migrations/**, tests/** | DONE — 99 tests green, verified independently, committed 07e780a |
| ui-scaffold | M0 Tauri shell | apps/ui/** | DONE — TS: 82 tests + strict tsc green (verified independently); Rust: cargo check GREEN on portable MSVC (no-admin toolchain at %LOCALAPPDATA%\portable-msvc, use setup_x64.bat env for all cargo runs). Zero protocol/token deviations. |
| m1-ears | dual capture + VAD + Parakeet streaming | engine/audio, engine/stt, tests | RUNNING |
| north-star #1 | read-only alignment review | (read-only) | DONE — 5 GREEN / 1 AMBER (tracker staleness, fixed); .env.example header fixed |
| engine-scaffold | M0 Python sidecar: WS server, protocol v1, migrations, CI, README | engine/**, migrations/**, tests/**, pyproject, ci.yml, README.md | RUNNING |
| ui-scaffold | M0 Tauri shell: tray, sidecar mgmt, heartbeat footer, protocol mirror | apps/ui/** (except tokens.css) | RUNNING |

## Pacing policy (user mandate, revised 2026-07-06 — binding)

Token quota is shared with the user's other running projects. **HARD CAP: 3 concurrent agents**
(user first corrected 1–2 as "too economical", then fixed the cap at 3), on genuinely disjoint
lanes (no shared files — pyproject/uv.lock reserved to one owner per phase). Model quality is NOT
the economy lever — Fable for anything design, language, landing-page, big, important, or
system-wide. No redundant re-verification of green work.

## Model decisions

- **STT stays parakeet-tdt-0.6b-v2** (checked 2026-07-06): newest is v3 (multilingual, 25 langs)
  but v2 is BETTER at English — 6.05% vs 6.34% WER (Open ASR leaderboard) — and Omni's primary
  use is English meetings. v3 = future config option for multilingual users (same size, drop-in).

## Test-economy policy (user mandate, 2026-07-06 — binding)

Tests stay rigorous and complete (unit + adversarial, no coverage compromise), but EXECUTION is
economical: agents run only the tests for code they touched + a fast targeted regression check.
The FULL suite runs once per milestone gate and on CI push — never re-run green for reassurance.

## Late-added scope

- **Pre-M3 research (user mandate):** AI-facing memory/retrieval layer over the vault — Obsidian
  stays the human layer; research hybrid retrieval (FTS5/BM25 + sqlite-vec dense), reranking,
  GraphRAG/entity indexes, temporal indexes, chunking. Peer-reviewed, docs/research/, evidence-backed
  recommendation BEFORE M3 is built. Queued: dispatch when an M0 agent slot frees (task #10).

- **M9 Landing page (after M7, user mandate):** scroll-animated aesthetic marketing page with REAL
  product screenshots (never mocks, §4.9.8), fades/motion as you scroll showing the product in use,
  GitHub-linked download (Releases) + bring-your-own-keys setup guide. GitHub Pages. Fable-built.
- **M10 Naomi voice agent (post-core, user mandate 2026-07-06, task #11):** Jarvis-style realtime
  voice agent — Cartesia voice (key + voice ID `7348…fedc` in `.env`, never committed), name Naomi.
  Millisecond retrieval over ALL user data (rides M3), real action execution (rides M4 + approval
  rules), document upload → general AI knowledge base, in-app Notion-like Obsidian viewer.
  Visual: black fluid "pool of water" that flows and reacts emotionally (laughing/happy/agitated) —
  design-critical, NOT plain white. Process: Fable RESEARCH agent first (fluid/shader/audio-reactive
  techniques, e.g. WebGL/WebGPU fluid sim, metaballs, FFT-driven motion + Cartesia realtime
  websocket pipeline + voice-agent turn loop), THEN Fable build agent briefed from that research.
  Naomi's speed showcase: end-to-end voice→answer latency displayed live (user's speed mandate).

## Gate state

- **Current gate:** M0. Green when: `pnpm tauri dev` shows live engine heartbeat in UI footer;
  sidecar survives kill/restart; migrations apply; repo pushed to GitHub with CI skeleton.
- Repo initialized, `.gitignore` + `.env.example` in place, Rust installed. Nothing else built yet.

## Blockers / waiting-on-user

- [ ] **MSVC C++ toolchain needs one elevated click (M0 Rust compile).** The box's VS2019 BuildTools
  is a skeleton (no cl.exe/link.exe/SDK); silent install requires admin and UAC auto-denies with
  nobody present. WHEN YOU'RE BACK, run in an elevated PowerShell (one command):
  `& "$env:LOCALAPPDATA\Temp\claude\C--dev-Omni\1a51eada-e8ae-4bb3-82f1-b9d977816f3d\scratchpad\vs_BuildTools.exe" --passive --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`
  (or just approve the UAC prompt if one is waiting). Meanwhile a no-admin portable-MSVC fallback
  is being attempted; M0 gate = everything green EXCEPT Rust compile verification. M1 (pure
  Python) proceeds in parallel — it does not need MSVC.

- [x] ~~GROQ_API_KEY + GEMINI_API_KEY~~ — present in `.env`, live-validated 2026-07-06
- [x] ~~/design-login~~ — done; design extracted and committed
- [ ] Google OAuth client ID/secret (needed for real M4 AC; mocks until then)
