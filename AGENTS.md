# AGENTS.md

This project uses the Superpowers framework. All agents must follow the Software Engineering workflow.

## Documentation

- Product overview: [README.md](README.md)
- Doc index: [docs/README.md](docs/README.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Features: [docs/features.md](docs/features.md)
- Operating contract: [CLAUDE.md](CLAUDE.md)

## Core Skills Available

- **brainstorm** — Use before coding to refine ideas.
- **write-plan** — Use to create detailed implementation plans.
- **execute-plan** — Use to implement code via TDD.
- **test-driven-development** — Always write tests first.
- **systematic-debugging** — Use for fixing bugs.

## Guardrails

- Read `.cursor/rules/manifest.mdc` for the Engineering Constitution.
- Always verify claims with evidence.
- Keep diffs small and focused.

## Project Structure

- `apps/ui/src-tauri/` — Rust backend (Tauri shell, sidecar supervisor, hotkeys)
- `apps/ui/src/` — Frontend (React + TypeScript)
- `engine/` — Python engine (FastAPI, WebSocket, STT, vault, router, dictation, export)
- `tests/` — pytest suite
- `docs/` — architecture, features, plans, threat model
