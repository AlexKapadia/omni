# Omni — Build Progress Tracker (durable, resume-from-death)

> **North Star:** Production-grade, local-first, bot-free meeting intelligence engine for Windows.
> Tauri 2 + React UI, Python engine sidecar (WASAPI loopback + mic → Silero VAD → Parakeet-TDT),
> Obsidian vault as source of truth, local RAG (bge-small + sqlite-vec), approval-carded agent
> actions, tri-provider router (Groq / Gemini / optional Anthropic), NSIS installer, auto-update.
> Open source on GitHub (AlexKapadia/omni) — no secrets ever committed.

**RESUME HERE →** ▶ RESUMED 20:23 2026-07-06 per schedule: three continuation agents dispatched
on branch wip/paused-lanes-20260706 (m2-enhance / m6-detect / m5-dictation). As each verifies
green: merge to main, flip ledger + this pointer in the same commit, then queue: M3 Ask-Omni
service → M4 (mocks until OAuth) → M7 ship → evidence/ + insane README (#12/#13) → M9 landing →
Naomi full loop. (Historical pause note:) ⏸ PAUSED 2026-07-06 ~18:5x. Main was clean and
green through the Naomi commit. Three lanes were stopped cleanly mid-flight; their partial work is
committed UNVERIFIED on branch **wip/paused-lanes-20260706** (pushed).

**RESUME PROTOCOL (do in order):**
1. `git checkout wip/paused-lanes-20260706` (or merge it into a fresh work branch) — the partial
   files live there; main stays clean until lanes verify green.
2. Respawn THREE Fable agents (cap 3), each told: "your lane's earlier agent was stopped mid-run;
   its partial files are on this branch — read them, keep what is good, finish to the original
   RETURN spec, verify (ruff/mypy/targeted pytest or vitest), report honestly":
   - **m2-enhance** (owns engine/enhance, engine/protocol additions, engine/server.py +
     websocket_connection_handler.py wiring, storage/migrations 0005/0006, UI meetings swap +
     library detail; binding: fidelity mandate, injection framing, live smoke w/ real keys).
     Stop-point: core pipeline files on disk; was starting the auto-stop monitor; server wiring
     NOT started.
   - **m6-detect** (owns engine/detect + tests; wiring deferred). Stop-point: core + 5 test files
     on disk; remaining: live Edge title-detection check + final verify + return.
   - **m5-dictation** (owns apps/ui/src-tauri hotkey+pill window, apps/ui/pill.html + src/pill,
     engine/dictation, migrations/0006→use 0007 if 0006 taken; wiring deferred; design doc §07
     pill spec). Stop-point: NO files on disk — respawn with full original scope.
3. After each lane verifies green: merge/commit to main (ledger row + RESUME HERE flip in the SAME
   commit), then continue queue: M3 Ask-Omni service → M4 (mocks until OAuth) → M7 ship →
   M9 landing → Naomi full loop (persistent Cartesia socket, turn orchestrator).
4. END-PHASE MANDATES (user, 2026-07-06 — tasks #12/#13): populate **evidence/** per §3.10
   (peer-reviewed stats, PNG+interactive-HTML graphs, aesthetic B&W flow diagrams per component +
   whole system, analysis-only deps manifest) and make the **README insane** per §4.9.8 — REAL
   product screenshots of every key screen (incl. Naomi's water), genuinely RECORDED video/GIF
   (Playwright recordVideo + ffmpeg, never mock/AI-generated), honest captions, judged by a
   separate evaluator agent that actually VIEWS the images. Both run when the real app is
   capturable (~M7), before/with M9 landing page.
5. The §4.8 watchdog cron (every 53 min, session-only) auto-fires this protocol if the session
   survived; if this is a FRESH session, this file + git + the task list are the whole state —
   act on this pointer directly. Scheduled one-shot auto-resume set for 20:23 2026-07-06.
RULE: every feature commit flips its ledger row + RESUME HERE in the SAME commit.

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
| M0 Skeleton | Tauri boots to tray, sidecar spawn+handshake+restart, migrations, CI skeleton | **DONE** (live boot AC: shell spawned engine, WS connected, /health ok, Parakeet on CUDA in sidecar, kill-on-exit verified) |
| M1 Ears | Dual-stream WASAPI+mic capture, VAD, streaming Parakeet, live Me/Them transcript | **DONE** (live-verified: verbatim loopback transcript, lag 898ms) |
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
| m1-ears | dual capture + VAD + Parakeet streaming | engine/audio, engine/stt, tests | DONE — 135 tests, live smoke passed, committed f01647b |
| north-star #1 | read-only alignment review | (read-only) | DONE — 5 GREEN / 1 AMBER (tracker staleness, fixed); .env.example header fixed |
| vault-writer | M2 core: Obsidian writers, managed regions | engine/vault, tests | DONE — 135 tests green (verified), committed. Managed markers are id-addressed: omni:managed:enhanced-notes/actions/transcript. |
| router | tri-provider router + DPAPI keys + ledger + kill switch | engine/router, engine/security, migrations/0003 | DONE — 172 tests, committed |
| ui-screens | Library / Live meeting / Ask Omni / Settings per design brief | apps/ui/src | DONE — 230 tests, committed |
| naomi-research | fluid-visual art + Cartesia voice pipeline research | docs/research/naomi, naomi-visual-brief.md | DONE — 10-source library + build contract, committed |
| m3-index | hybrid retrieval index per research contract | engine/index, migrations/0004, tests | DONE — 123 tests (665 repo), committed. Dense side degrades to BM25-only until vec model ships; reranker interface chat-gated. |
| naomi-build | fluid visual + Cartesia voice foundation per brief | apps/ui/src/naomi, engine/voice | DONE — 135 UI + 65 engine tests, live Cartesia TTFA 469–610ms (cold-connect dominated; persistent socket = loop TODO), committed |
| m2-enhance | enhance pipeline, templates, extraction, finalization, auto-stop | engine/enhance, server wiring, UI meetings swap | RUNNING |
| m6-detect | process/window watch, mic-in-use, VAD trigger, rules engine | engine/detect, tests | DONE on wip branch — predecessor's code fully validated, 120 tests green (verified), live Edge/Meet detection fired t=3s, idle apps correctly sub-threshold. Server wiring deferred (interface in agent return + module docstrings). Merges to main with the branch. |
| m3-ask | Ask-Omni answer service + live answers spotter | engine/ask, ask-screen/stores | DONE — 26 py + 33 ts tests, live smoke: verified citations, honest no-answer, structured path 1.0s. Wiring deferred (spec in engine/ask/__init__). Committed 1c0e05d. |
| m5-dictation | hotkey + pill + note/command modes (original scope) | src-tauri, src/pill, engine/dictation | DONE — 98 py + 95 ts tests, live: real intent JSON 800ms, real Inbox note w/ Groq title. Wispr-Flow-raise seams left clean. Wiring deferred (dictation_protocol_names.py). |
| slow-provider-cancel test | orchestrator: pin wait_for cancellation at budget (m3-ask flag) | tests/test_router__slow_provider… | DONE — proves a hanging provider is cancelled at timeout_seconds; the observed 12.1s was multi-attempt wall time (legitimate). |
| north-star #2 | read-only alignment review | (read-only) | DONE — 4 GREEN / 2 AMBER (stt file split + this tracker fix) |

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

- **Dictation bar raised (user mandate, 2026-07-06): must beat Wispr Flow.** Added to the M5 lane
  mid-flight: universal text injection into any focused Windows app (clipboard-swap + SendInput),
  intelligent cleanup via new router task "dictation_cleanup" (fillers out, self-corrections
  resolved, meaning never changed, RAW verbatim always retained), release→text <1.2s budget with
  real measured numbers, personal dictionary file. Router-down → raw verbatim still lands.

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

- **Current gate:** the WIRING RECONCILIATION PASS + batch merge to main. M0+M1 gates DONE
  (live-verified). Landed on wip branch awaiting merge: M3 index+ask, M5 dictation, M6 detect,
  Naomi foundation. M2 enhance in flight. M3/M5/M6 milestone gates close only after the wiring
  pass (see RESUME HERE) wires their deferred server surfaces and the merged suite runs green.

## Blockers / waiting-on-user

- [x] ~~MSVC C++ toolchain~~ — RESOLVED via portable-MSVC (no-admin, %LOCALAPPDATA%\portable-msvc);
  the elevated VS install is optional now. Original note: The box's VS2019 BuildTools
  is a skeleton (no cl.exe/link.exe/SDK); silent install requires admin and UAC auto-denies with
  nobody present. WHEN YOU'RE BACK, run in an elevated PowerShell (one command):
  `& "$env:LOCALAPPDATA\Temp\claude\C--dev-Omni\1a51eada-e8ae-4bb3-82f1-b9d977816f3d\scratchpad\vs_BuildTools.exe" --passive --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`
  (or just approve the UAC prompt if one is waiting). Meanwhile a no-admin portable-MSVC fallback
  is being attempted; M0 gate = everything green EXCEPT Rust compile verification. M1 (pure
  Python) proceeds in parallel — it does not need MSVC.

- [x] ~~GROQ_API_KEY + GEMINI_API_KEY~~ — present in `.env`, live-validated 2026-07-06
- [x] ~~/design-login~~ — done; design extracted and committed
- [ ] Google OAuth client ID/secret (needed for real M4 AC; mocks until then)
