# Omni

**Local-first, bot-free meeting intelligence for Windows.**

Omni sits quietly on your machine, captures your meetings as two clean labelled streams — system audio via WASAPI loopback (the other participants, headphone-proof) and your microphone (you) — transcribes everything **on-device**, and turns your rough notes plus the transcript into enhanced, structured notes in your Obsidian vault. No bot joins your calls. No audio ever leaves your machine. No telemetry, ever.

## What it does

- **Invisible capture** — records meetings without a bot: WASAPI loopback for remote participants + your mic for you, labelled `them` / `me`. Works with headphones.
- **On-device transcription** — Silero VAD gating a streaming Parakeet-TDT model. Audio is discarded after transcription by default; keeping it is an explicit opt-in.
- **Your vault is the source of truth** — Omni reads and writes Markdown in your Obsidian vault. It only creates new files or appends inside clearly-marked managed regions; your own words are never edited.
- **Enhanced notes** — your rough in-meeting notes are fused with the transcript into clean, structured meeting notes.
- **Ask anything, live** — a local RAG index (bge-small embeddings in sqlite-vec) over your vault and every past transcript answers questions during and after meetings.
- **Approval-carded actions** — Omni proposes actions (calendar events, contact upserts, Gmail **drafts — it never sends**); nothing executes without your explicit approval. Every executed action lands in an append-only audit log.
- **Tri-provider AI router** — Groq for instant work, Gemini Flash for long-context bulk, and (optionally) Claude for agentic tool use and synthesis. You bring your own keys; the router sends the minimum excerpt each task needs.
- **Dictation** — global push-to-talk dictation into any app.
- **Ships like a real product** — Tauri 2 app (React frontend) with a PyInstaller Python engine sidecar, one-click NSIS installer, auto-update.

## Privacy model (non-negotiable)

- **Local-first**: transcripts, embeddings, notes, and keys never leave your machine, except the minimum excerpts inside model calls you configured.
- **Audio is never uploaded anywhere** and is deleted after transcription unless you opt in to keeping it.
- **Zero telemetry.** None.
- **Your keys, encrypted**: API keys are supplied by you at onboarding and encrypted with Windows DPAPI (per-user). They are never written to disk in plaintext and never logged. Only the engine process holds them — the UI never does.
- **Kill-switch**: one flag halts all external calls. Capture, transcription, and your vault keep working fully offline.
- **Append-only audit log** of every executed action and every external model call: what, when, which provider.

## Architecture

```
apps/ui/          Tauri 2 shell + React frontend (tray, hotkeys, approval cards)
engine/           Python engine sidecar (PyInstaller-packed)
  protocol/       Pinned WebSocket protocol v1 (UI <-> engine)
  storage/        SQLite (aiosqlite) + migrations runner
  audio/          WASAPI loopback + mic capture          (upcoming)
  stt/            Silero VAD + Parakeet streaming        (upcoming)
  index/          Chunker, bge-small embedder, sqlite-vec (upcoming)
  router/         Groq / Gemini / Claude routing          (upcoming)
  agents/         Extraction, approval cards, executor    (upcoming)
  vault/          Obsidian Markdown writers               (upcoming)
  server.py       FastAPI + WS server (127.0.0.1 only)
migrations/       Ordered SQL migrations
tests/            Engine test suite (pytest)
```

The engine binds to `127.0.0.1` **only** and speaks a small versioned WebSocket protocol to the UI (`ws://127.0.0.1:8765/ws`, port via `OMNI_ENGINE_PORT`). `GET /health` reports liveness.

## Quick start (developers)

Prerequisites: **[uv](https://docs.astral.sh/uv/)** (Python toolchain) and **[pnpm](https://pnpm.io/)** (UI, once `apps/ui` lands). Python 3.11 is pinned and installed automatically by uv.

```bash
git clone https://github.com/AlexKapadia/omni
cd omni

# Engine: install deps (uv provisions Python 3.11 itself)
uv sync

# Run the checks
uv run ruff check .
uv run mypy
uv run pytest

# Run the engine sidecar
uv run python -m engine.server
# -> GET http://127.0.0.1:8765/health  =>  {"status":"ok","version":"0.1.0"}

# UI (once apps/ui exists)
cd apps/ui && pnpm install && pnpm dev
```

On Linux/macOS the same commands are wrapped as `make test`, `make lint`, `make typecheck`, `make run`.

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OMNI_ENGINE_PORT` | `8765` | HTTP + WS port (always bound to 127.0.0.1) |
| `OMNI_DB_PATH` | `%LOCALAPPDATA%/Omni/omni.db` | SQLite database location |

## Bring your own keys

Omni has no backend and no accounts — the AI features run on **your** API keys:

- **Groq** — fast, cheap calls (live answers, quick extraction).
- **Google Gemini (Flash)** — long-context bulk work (full-transcript passes).
- **Anthropic Claude** *(optional)* — agentic tool use and high-quality synthesis.

You enter keys once during onboarding. They are DPAPI-encrypted per Windows user, never stored in plaintext, never logged, and never leave your machine. Any provider you skip is simply not used; with no keys at all, capture, transcription, and vault features still work fully offline.

## Status

Early development (M0): engine skeleton — WebSocket protocol v1, SQLite storage with migrations, health/heartbeat. Audio capture and STT are next.

## License

Proprietary. All rights reserved.
