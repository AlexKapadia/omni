# AGENTS.md

This project uses the Superpowers framework. All agents must follow the Software Engineering workflow.

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

- `apps/ui/src-tauri/` — Rust backend (Tauri shell)
- `apps/ui/src/` — Frontend (React + TypeScript)
- `engine/` — Python engine (FastAPI, WebSocket, STT, vault, router)
- `tests/` — pytest suite
