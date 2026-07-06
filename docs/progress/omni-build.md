# Omni — Build Progress Tracker (durable, resume-from-death)

> **North Star:** Production-grade, local-first, bot-free meeting intelligence engine for Windows.
> Tauri 2 + React UI, Python engine sidecar (WASAPI loopback + mic → Silero VAD → Parakeet-TDT),
> Obsidian vault as source of truth, local RAG (bge-small + sqlite-vec), approval-carded agent
> actions, tri-provider router (Groq / Gemini / optional Anthropic), NSIS installer, auto-update.
> Open source on GitHub (AlexKapadia/omni) — no secrets ever committed.

**RESUME HERE →** M0 in progress: dispatch scaffolding agents (UI shell, engine sidecar, migrations, CI).

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
| _(none yet)_ | | | |

## Gate state

- **Current gate:** M0. Green when: `pnpm tauri dev` shows live engine heartbeat in UI footer;
  sidecar survives kill/restart; migrations apply; repo pushed to GitHub with CI skeleton.
- Repo initialized, `.gitignore` + `.env.example` in place, Rust installed. Nothing else built yet.

## Blockers / waiting-on-user

- [ ] GROQ_API_KEY + GEMINI_API_KEY in `.env` (needed from M2)
- [ ] `/design-login` for design token extraction (workaround: token defaults + TODO(design))
- [ ] Google OAuth client ID/secret (needed for real M4 AC; mocks until then)
